<template>
  <canvas ref="canvasEl" class="butler-canvas" />
</template>

<script setup>
/**
 * 三维虚拟管家头像（three.js 程序化建模）。
 *
 * 刻意不加载任何模型文件 —— 也就意味着没有任何网络请求：整个形象是球、圆柱、
 * 圆锥在运行时拼出来的。要真 3D 的原因很实际：这颗头会缓慢地左右转、上下浮，
 * 透视和前后遮挡都是算出来的，而不是画出来的，轮廓会随着转动真正变形。
 *
 * 造型（圆润机器人管家）：
 *   头部   一颗略微压扁的球，深色金属壳，腰上一道凹槽把它切成上下两半
 *   眼缝   从球面上切下来、两端收尖的一条横带 —— 脸上唯一发光、也是唯一会「说话」的地方
 *   耳罩   两侧圆柱 + 外端一圈亮环
 *   天线   细杆顶着一颗亮珠，慢慢明灭
 *   领口   圆柱 + 一圈环
 *   领结   两只对顶的圆锥，是「管家」这个身份的标志
 *
 * 轮廓那圈青光不是贴图，是同一个形状放大一圈、用菲涅尔 (1 - N·V) 算出来的加法
 * 混合外壳：正对镜头的地方几乎透明，越掠到边缘越亮。全息投影的质感就来自这里。
 *
 * 渲染注意：alpha 必须开、并且把清屏色设成全透明 —— canvas 一旦有不透明底色，
 * 外层那颗 CSS 线框球就会被整块盖住。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AdditiveBlending,
  AmbientLight,
  BoxGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DirectionalLight,
  Group,
  MathUtils,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PerspectiveCamera,
  Scene,
  ShaderMaterial,
  SphereGeometry,
  TorusGeometry,
  Vector3,
  WebGLRenderer
} from 'three'

const props = defineProps({
  /** 正在聆听：眼带更亮、脉动更快，转动幅度稍大。 */
  listening: { type: Boolean, default: false },
  /** 正在回话：眼带最亮最快，整个形象也更活跃。 */
  speaking: { type: Boolean, default: false }
  , assembling: { type: Boolean, default: true }
})

const canvasEl = ref(null)

/* 主体的几何常量：头部半径定为 1，其余尺寸全部按它推。 */
const R = 1

/* 眼缝所在的高度。three 的球是 phi=90° 落在 +Z（正面），theta 从北极量起，
 * 90° 就是赤道 —— 取 90° 把这条缝摆在脸的当中。往上抬会顶到头顶那道腰线凹槽，
 * 额头上就一点留白都没有了；往下压又会掉到下巴上。 */
const EYE = { lat: 90 }

let renderer = null
let scene = null
let camera = null
let figure = null
let eyeGlowMat = null
let eyeMidMat = null
let eyeCoreMat = null
let antennaTipMat = null
let fragments = []
let fragmentGroup = null
let rafId = 0
let observer = null
let t = 0
let lastTime = 0

/* 状态量都走「目标值 + 每帧插值」，切换聆听/回话时是滑过去的，不会跳。 */
const cur = { glow: 0.58, core: 0.44, sway: 0.34, bob: 0.85 }
const want = { glow: 0.58, core: 0.44, sway: 0.34, bob: 0.85 }

/** 收集所有要手动释放的几何体/材质，卸载时一次清干净。 */
const trash = []
const keep = item => {
  trash.push(item)
  return item
}

/**
 * 眼带：从球面上切下来、两端收成尖的一条横带。
 *
 * 收口是这段的关键。等纬度带在正面看就是一块方正的矩形 —— 它的上下两缘是两条平行圈，
 * 投影出来是直线，贴在脸上像贴了张屏幕。所以切完之后要逐个顶点把上下两缘往中心纬度挤，
 * 挤的力度按「离正脸多远」衰减（sin 曲线），两端收到 0，出来才是一条杏仁形眼缝。
 */
function visorBand(radius, phiStartDeg, phiLenDeg, thetaCenterDeg, thetaHalfDeg, taperPow, segs) {
  const geo = keep(
    new SphereGeometry(
      radius,
      segs || 128,
      20,
      MathUtils.degToRad(phiStartDeg),
      MathUtils.degToRad(phiLenDeg),
      MathUtils.degToRad(thetaCenterDeg - thetaHalfDeg),
      MathUtils.degToRad(thetaHalfDeg * 2)
    )
  )
  const pos = geo.attributes.position
  const v = new Vector3()
  const phi0 = MathUtils.degToRad(phiStartDeg)
  const phiSpan = MathUtils.degToRad(phiLenDeg)
  const thetaC = MathUtils.degToRad(thetaCenterDeg)
  for (let i = 0; i < pos.count; i += 1) {
    v.fromBufferAttribute(pos, i)
    const len = v.length()
    // 反推球面参数。three 的顶点公式是 x=-r·cosφ·sinθ、z=r·sinφ·sinθ，
    // 所以 atan2(z, -x) 正好还原出 φ，θ 从北极算起就是 acos(y/r)。
    const phi = Math.atan2(v.z, -v.x)
    const theta = Math.acos(MathUtils.clamp(v.y / len, -1, 1))
    // u：0 在带子的一头、1 在另一头，k 在两端为 0、正中为 1
    const u = MathUtils.clamp((phi - phi0) / phiSpan, 0, 1)
    const k = Math.pow(Math.sin(Math.PI * u), taperPow)
    const th = thetaC + (theta - thetaC) * k
    const sin = Math.sin(th)
    v.set(-len * Math.cos(phi) * sin, len * Math.cos(th), len * sin * Math.sin(phi))
    pos.setXYZ(i, v.x, v.y, v.z)
  }
  pos.needsUpdate = true
  return geo
}

/** 眼缝的一层发光材质。不透明度由动画循环按状态改，这里只定颜色和混合方式。 */
function eyeMaterial(color) {
  return keep(
    new MeshBasicMaterial({
      color: new Color(color),
      transparent: true,
      opacity: 0.4,
      blending: AdditiveBlending,
      depthWrite: false
    })
  )
}

/** 菲涅尔外壳：正对镜头透明，边缘发亮。全息轮廓光全靠它。 */
function rimShell(geometry, { color, power, intensity, scale = 1 }) {
  const mat = keep(
    new ShaderMaterial({
      uniforms: {
        uColor: { value: new Color(color) },
        uPower: { value: power },
        uIntensity: { value: intensity }
      },
      vertexShader: `
        varying vec3 vN;
        varying vec3 vV;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vN = normalize(normalMatrix * normal);
          vV = normalize(-mv.xyz);
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        uniform vec3 uColor;
        uniform float uPower;
        uniform float uIntensity;
        varying vec3 vN;
        varying vec3 vV;
        void main() {
          float f = pow(1.0 - clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0), uPower);
          gl_FragColor = vec4(uColor * f * uIntensity, 1.0);
        }
      `,
      transparent: true,
      blending: AdditiveBlending,
      depthWrite: false
    })
  )
  const mesh = new Mesh(geometry, mat)
  mesh.scale.setScalar(scale)
  return mesh
}

/** 深色金属外壳材质：全息体是发光的，本体要压得够暗才衬得出光。 */
function shellMaterial(color, extra = {}) {
  return keep(
    new MeshStandardMaterial({
      color,
      metalness: 0.68,
      roughness: 0.3,
      emissive: 0x0a2b42,
      emissiveIntensity: 0.45,
      ...extra
    })
  )
}

function buildHead(parent) {
  // 头部：收窄成面甲轮廓，保留全息球体的透明感，同时增加装甲切面。
  const headGeo = keep(new SphereGeometry(R, 72, 54))
  headGeo.scale(1, 1.06, 0.97)
  const head = new Mesh(headGeo, shellMaterial(0x0d2739))
  parent.add(head)

  // 外壳的菲涅尔光圈：微微放大一圈套在外面。壳压得暗，轮廓全靠它撑起来，
  // 所以给得比别的部件狠 —— power 调小等于把亮边铺宽，不至于只剩一圈细描边。
  parent.add(rimShell(headGeo, { color: 0x67e8f9, power: 2.1, intensity: 1.6, scale: 1.035 }))

  // 腰线凹槽：一道细环，把球面切成上下两半，机器感就是它给的。
  const grooveY = 0.42
  const grooveR = Math.sqrt(Math.max(R * R - grooveY * grooveY, 0.01)) * 1.002
  const groove = new Mesh(
    keep(new TorusGeometry(grooveR, 0.022, 12, 96)),
    keep(new MeshStandardMaterial({ color: 0x061420, metalness: 0.9, roughness: 0.55 }))
  )
  groove.rotation.x = Math.PI / 2
  groove.position.y = grooveY
  parent.add(groove)

}

function buildVisor(parent) {
  // 由外到内三层同心带，全部加色混合：中心三层叠在一起最亮，往外只剩最外一层，
  // 从亮芯到边缘的渐变是叠出来的，不用贴图。
  //
  // phi 的跨度要收着给。正面是 phi=90°、两侧耳罩在 phi=0/180°，原来 24°–156°
  // 等于把整个正面都铺满，读起来是横贯脸上的一条带子而不是眼睛；收到 42°–138°
  // 之后两端各离耳罩还有 42°，才有一张「脸」的比例。
  eyeGlowMat = keep(eyeMaterial(0x1a9fd8))
  parent.add(new Mesh(visorBand(R * 1.006, 42, 96, EYE.lat, 12.5, 0.55), eyeGlowMat))

  eyeMidMat = keep(eyeMaterial(0x46ccff))
  parent.add(new Mesh(visorBand(R * 1.013, 54, 72, EYE.lat, 8, 0.5), eyeMidMat))

  eyeCoreMat = keep(eyeMaterial(0xeafcff))
  parent.add(new Mesh(visorBand(R * 1.019, 64, 52, EYE.lat, 3.8, 0.45), eyeCoreMat))

  // 暗玻璃罩：比眼缝大一圈把它罩住，只留一点清漆般的反光。
  // 粗糙度不能给太小、不透明度也不能给太高：金属度 0.95 配 0.06 的镜面会把
  // 打过来的方向光摊成一大片灰白高光，正好糊在眼缝上，青光就被洗成奶灰色了。
  const glass = new Mesh(
    visorBand(R * 1.03, 32, 116, EYE.lat, 15.5, 0.6),
    keep(
      new MeshStandardMaterial({
        color: 0x040d16,
        metalness: 0.9,
        roughness: 0.22,
        transparent: true,
        opacity: 0.16,
        depthWrite: false
      })
    )
  )
  parent.add(glass)
}

function buildEars(parent) {
  const shellMat = shellMaterial(0x0b2233, { roughness: 0.26 })
  const ringMat = keep(
    new MeshBasicMaterial({
      color: new Color(0x7fe6ff),
      transparent: true,
      opacity: 0.85,
      blending: AdditiveBlending,
      depthWrite: false
    })
  )
  for (const side of [-1, 1]) {
    const cup = new Mesh(keep(new CylinderGeometry(0.3, 0.32, 0.2, 40)), shellMat)
    cup.rotation.z = Math.PI / 2
    cup.position.set(side * 1.0, 0.03, 0)
    parent.add(cup)

    const ring = new Mesh(keep(new TorusGeometry(0.17, 0.03, 12, 48)), ringMat)
    ring.rotation.y = Math.PI / 2
    ring.position.set(side * 1.11, 0.03, 0)
    parent.add(ring)
  }
}

function buildAntenna(parent) {
  const stalk = new Mesh(keep(new CylinderGeometry(0.026, 0.034, 0.36, 20)), shellMaterial(0x0b2233))
  stalk.position.y = 1.2
  parent.add(stalk)

  antennaTipMat = keep(
    new MeshBasicMaterial({
      color: new Color(0xa9f0ff),
      transparent: true,
      opacity: 0.9,
      blending: AdditiveBlending,
      depthWrite: false
    })
  )
  const tip = new Mesh(keep(new SphereGeometry(0.082, 24, 18)), antennaTipMat)
  tip.position.y = 1.44
  parent.add(tip)

  // 亮珠外面再裹一层柔光，免得它只是一颗硬邦邦的小球。
  const halo = new Mesh(keep(new SphereGeometry(0.16, 20, 14)), antennaTipMat.clone())
  halo.material.opacity = 0.16
  halo.position.y = 1.44
  keep(halo.material)
  parent.add(halo)
}

function buildCollar(parent) {
  const collar = new Mesh(
    keep(new CylinderGeometry(0.38, 0.5, 0.28, 48, 1, true)),
    shellMaterial(0x0a1f30, { side: 2, roughness: 0.36 })
  )
  collar.position.y = -1.19
  parent.add(collar)

  const ring = new Mesh(keep(new TorusGeometry(0.45, 0.045, 14, 64)), shellMaterial(0x10384f))
  ring.rotation.x = Math.PI / 2
  ring.position.y = -1.3
  parent.add(ring)
}

function buildBowtie(parent) {
  // 颜色给得比别的部件亮、还带一点自发光：领口那片本来就压得很暗，
  // 不这样提一把，领结在这个尺寸下只是一团黑。
  const mat = shellMaterial(0x1c5878, { metalness: 0.72, roughness: 0.2, emissive: 0x0d3a52, emissiveIntensity: 0.75 })
  const wingGeo = keep(new ConeGeometry(0.19, 0.36, 4))
  for (const side of [-1, 1]) {
    const wing = new Mesh(wingGeo, mat)
    // 圆锥默认尖朝 +Y，转 90° 让两只的尖端在中间对顶，就是领结的形状。
    wing.rotation.z = side * (Math.PI / 2)
    wing.rotation.y = Math.PI / 4
    wing.position.set(side * 0.17, -1.12, 0.45)
    parent.add(wing)
  }
  const knot = new Mesh(keep(new SphereGeometry(0.072, 20, 14)), shellMaterial(0x3585ad, { metalness: 0.6, emissive: 0x14506e, emissiveIntensity: 0.8 }))
  knot.position.set(0, -1.12, 0.47)
  parent.add(knot)
}

function build() {
  scene = new Scene()

  figure = new Group()
  scene.add(figure)

  // 四向散落的金属碎片：进入全息态时沿着各自的轨道回到面甲轮廓。
  fragmentGroup = new Group()
  scene.add(fragmentGroup)
  const shardMat = keep(new MeshBasicMaterial({ color: 0x65e6ff, transparent: true, opacity: 0.72, blending: AdditiveBlending }))
  for (let i = 0; i < 42; i += 1) {
    const angle = (i / 42) * Math.PI * 2
    const radius = 1.35 + (i % 5) * 0.16
    const shard = new Mesh(keep(new BoxGeometry(0.035 + (i % 3) * 0.018, 0.11 + (i % 4) * 0.035, 0.018)), shardMat)
    shard.userData.from = new Vector3(Math.cos(angle) * radius * 2.4, Math.sin(angle) * radius * 1.55, (i % 7 - 3) * 0.35)
    shard.userData.to = new Vector3(Math.cos(angle) * radius * 0.62, Math.sin(angle) * radius * 0.55, 0.22 + (i % 4) * 0.06)
    shard.position.copy(shard.userData.from)
    shard.rotation.set(Math.sin(angle) * 1.4, angle, Math.cos(angle) * 1.2)
    fragmentGroup.add(shard)
    fragments.push(shard)
  }

  buildHead(figure)
  buildVisor(figure)
  buildEars(figure)
  buildAntenna(figure)
  buildCollar(figure)
  buildBowtie(figure)

  // 打光：环境光压低，主光从右前上打，青色轮廓光从背后勾边，
  // 底部再补一盏冷光，免得下颌和领口糊成一片黑。
  scene.add(new AmbientLight(0x1b3d5c, 1.35))
  const key = new DirectionalLight(0xdcf6ff, 2.6)
  key.position.set(4, 5, 7)
  scene.add(key)
  const rim = new DirectionalLight(0x38bdf8, 3.6)
  rim.position.set(-4, 2, -6)
  scene.add(rim)
  const fill = new DirectionalLight(0x22d3ee, 1.1)
  fill.position.set(0, -4, 4)
  scene.add(fill)

  camera = new PerspectiveCamera(30, 1, 0.1, 50)
  camera.position.set(0, 0.12, 5.7)
  camera.lookAt(new Vector3(0, 0.05, 0))
}

function resize() {
  const el = canvasEl.value
  if (!el || !renderer) return
  const w = el.clientWidth
  const h = el.clientHeight
  if (!w || !h) return
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setSize(w, h, false)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}

function frame(now) {
  rafId = requestAnimationFrame(frame)
  const dt = lastTime ? Math.min((now - lastTime) / 1000, 0.05) : 0.016
  lastTime = now
  t += dt
  const assembly = props.assembling ? MathUtils.clamp((t - 0.1) / 2.7, 0, 1) : 1
  const eased = 1 - Math.pow(1 - assembly, 3)
  fragments.forEach((shard, index) => {
    const delay = (index % 7) * 0.035
    const p = MathUtils.clamp((assembly - delay) / (1 - delay), 0, 1)
    const e = 1 - Math.pow(1 - p, 2)
    shard.position.lerpVectors(shard.userData.from, shard.userData.to, e)
    shard.rotation.x += dt * (1.5 + index % 3)
    shard.rotation.y += dt * (1.1 + index % 4)
    shard.material.opacity = (1 - e) * 0.8
  })
  fragmentGroup.rotation.y = t * 0.12
  figure.visible = assembly > 0.72
  figure.scale.setScalar(Math.max(0.01, eased))

  // 状态之间滑过去，不硬切。
  const k = 1 - Math.pow(0.0015, dt)
  cur.glow = MathUtils.lerp(cur.glow, want.glow, k)
  cur.core = MathUtils.lerp(cur.core, want.core, k)
  cur.sway = MathUtils.lerp(cur.sway, want.sway, k)
  cur.bob = MathUtils.lerp(cur.bob, want.bob, k)

  // 眼缝是脸上唯一会「说话」的地方：一条明灭的亮缝，快慢跟着状态走。
  // 三层是加色叠起来的，单层不能给太满 —— 中间三层一叠已经过 1，那正是亮芯。
  const pulse = 0.5 + 0.5 * Math.sin(t * (1.6 + cur.glow * 2.4))
  eyeGlowMat.opacity = MathUtils.clamp(cur.glow * (0.38 + pulse * 0.32), 0, 1)
  eyeMidMat.opacity = MathUtils.clamp(cur.core * (0.34 + pulse * 0.32), 0, 1)
  eyeCoreMat.opacity = MathUtils.clamp(cur.core * (0.46 + pulse * 0.44), 0, 1)
  // 天线的亮珠慢半拍地明灭，和眼带错开，整颗头才不像只在闪一个地方。
  antennaTipMat.opacity = 0.45 + 0.5 * (0.5 + 0.5 * Math.sin(t * 1.1 + 1.4))

  // 转身 + 上下浮 + 轻微点头：三个周期互质，合起来看不出重复。
  figure.rotation.y = Math.sin(t * cur.sway) * 0.52
  figure.rotation.x = Math.sin(t * cur.sway * 0.83) * 0.055
  figure.position.y = Math.sin(t * cur.bob) * 0.045

  renderer.render(scene, camera)
}

function applyState() {
  const speaking = props.speaking
  const listening = props.listening && !speaking
  if (speaking) {
    want.glow = 1.0
    want.core = 1.0
    want.sway = 0.62
    want.bob = 1.5
  } else if (listening) {
    want.glow = 0.8
    want.core = 0.66
    want.sway = 0.5
    want.bob = 1.15
  } else {
    want.glow = 0.58
    want.core = 0.44
    want.sway = 0.34
    want.bob = 0.85
  }
}

watch(() => [props.listening, props.speaking], applyState)

onMounted(() => {
  const canvas = canvasEl.value
  if (!canvas) return
  renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' })
  renderer.setClearColor(0x000000, 0)

  build()
  applyState()
  cur.glow = want.glow
  cur.core = want.core
  resize()

  observer = new ResizeObserver(resize)
  observer.observe(canvas)

  rafId = requestAnimationFrame(frame)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  if (observer) {
    observer.disconnect()
    observer = null
  }
  // 显式释放：几何体、材质、贴图都不归 GC 管，不 dispose 就是漏显存。
  trash.forEach(item => item.dispose?.())
  trash.length = 0
  if (renderer) {
    renderer.dispose()
    renderer.forceContextLoss()
    renderer = null
  }
  scene = null
  camera = null
  figure = null
  fragments = []
  fragmentGroup = null
  eyeGlowMat = null
  eyeMidMat = null
  eyeCoreMat = null
  antennaTipMat = null
})
</script>

<style scoped>
.butler-canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
