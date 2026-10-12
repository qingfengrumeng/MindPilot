"""Read system voices from the vendor's public, model-specific voice tables."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx


class VoiceListError(ValueError):
    pass


class VoiceTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records, self.cells, self.parts = [], [], []
        self.capture, self.level, self.cell = None, 0, False
        self.samples = []

    def handle_starttag(self, tag, attrs):
        if tag in {'audio', 'source'}:
            source = dict(attrs).get('src', '')
            parts = urlsplit(source)
            if parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password:
                self.samples.append(source)
        if tag in {'td', 'th'}:
            self.cell = True
            self.parts = []
        elif not self.cell and tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'}:
            self.capture = tag
            self.parts = []

    def handle_data(self, text):
        if self.cell or self.capture:
            if text.strip():
                self.parts.append(text.strip())

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell:
            self.cells.append('\n'.join(self.parts))
            self.cell, self.parts = False, []
        elif tag == 'tr':
            if self.cells:
                self.records.append(('row', 0, {'cells':self.cells, 'samples':self.samples}))
            self.cells, self.samples = [], []
        elif tag == self.capture and not self.cell:
            self.records.append(('p' if tag == 'p' else 'h', int(tag[1]) if tag != 'p' else 0, ' '.join(self.parts)))
            self.capture, self.parts = None, []


def document_html(page):
    marker = re.search(r'window\.__ICE_PAGE_PROPS__\s*=\s*', page)
    if marker:
        try:
            props = json.JSONDecoder().raw_decode(page[marker.end():])[0]
            return props['docDetailData']['storeData']['data']['content']
        except (ValueError, KeyError, TypeError):
            raise VoiceListError('官方音色文档格式已变化，请稍后重试') from None
    return page


def parse_system_voices(page, model):
    parser = VoiceTableParser()
    parser.feed(document_html(page))
    active, scope, heading = False, 0, 1
    voice_column = None
    detail_columns = []
    voices = {}
    model_token = re.compile(r'(?<![\w.-])' + re.escape(model) + r'(?![\w-]|\.[\w])', re.I)
    for kind, level, value in parser.records:
        if kind == 'h':
            heading = level
            if level <= scope:
                active = False
            voice_column = None
            detail_columns = []
            if model_token.search(value):
                active, scope = True, level
        elif kind == 'p' and model_token.search(value):
            active, scope = True, heading
        elif kind == 'row' and active:
            samples = value['samples']
            value = value['cells']
            columns = [index for index, cell in enumerate(value) if cell.strip().lower() in {'性别', '音色特点', '适用场景', 'gender', 'voice characteristics', 'use cases'}]
            if columns:
                detail_columns = columns
            for index, cell in enumerate(value):
                if re.fullmatch(r'(?:voice\s*(?:id|parameter|参数)|音色参数)', cell.strip(), re.I):
                    voice_column = index
                    break
            else:
                voice_id, name = None, ''
                if voice_column is not None and len(value) > voice_column:
                    candidate = value[voice_column].strip()
                    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,150}', candidate):
                        voice_id, name = candidate, value[0].strip()
                if not voice_id:
                    for cell in value:
                        match = re.search(r'(?:voice\s*(?:parameter|参数)|音色参数)\s*[:：]?\s*([^\n]+)', cell, re.I)
                        if not match:
                            continue
                        candidate = re.split(r'\s*(?:Description|Characteristic|Attribute|描述|特点|性别|年龄)\s*[:：]', match[1], flags=re.I)[0].strip()
                        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,150}', candidate):
                            voice_id = candidate
                            label = re.search(r'(?:Name|名称)\s*[:：]\s*([^\n]+)', cell, re.I)
                            name = label[1].strip() if label else candidate
                            break
                if voice_id:
                    voice = {'id': voice_id, 'name': name or voice_id}
                    descriptions = [re.sub(r'\s+', ' ', value[index]).strip() for index in detail_columns if index < len(value) and value[index].strip()]
                    if not descriptions:
                        for cell in value:
                            for match in re.finditer(r'(?:Gender|Attribute|Description|性别|属性|描述|特点)\s*[:：]?\s*([^\n]+)', cell, re.I):
                                descriptions.append(match[1].strip())
                    if descriptions:
                        voice['description'] = ' · '.join(descriptions)[:250]
                    if samples:
                        voice['previewUrl'] = samples[0]
                    voices[voice_id] = voice
    return list(voices.values())


def fetch_system_voices(model):
    if model.startswith('qwen-audio-'):
        page_name = 'qwen-audio-tts-voice-list'
    elif model.startswith('cosyvoice-'):
        page_name = 'cosyvoice-voice-list'
    elif model.startswith('qwen3-tts-'):
        page_name = 'qwen-tts-voice-list'
    else:
        raise VoiceListError('该模型尚未接入官方系统音色列表，可手动填写音色 ID')
    url = f'https://help.aliyun.com/zh/model-studio/{page_name}'
    try:
        with httpx.Client(timeout=25, follow_redirects=False, trust_env=False) as client:
            response = client.get(url)
            response.raise_for_status()
            voices = parse_system_voices(response.text, model)
    except (httpx.HTTPError, ValueError, TypeError):
        raise VoiceListError('无法获取官方音色列表，请稍后重试或手动填写音色 ID') from None
    if not voices:
        raise VoiceListError('官方文档暂无该型号的系统音色列表，可手动填写音色 ID')
    return {'model': model, 'voices': voices, 'sourceUrl': url, 'sourceType': 'official-system-voices'}
