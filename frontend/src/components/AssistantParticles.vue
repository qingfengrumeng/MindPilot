<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { NormalBlending, BufferGeometry, Float32BufferAttribute, Group, Mesh, MeshBasicMaterial, PerspectiveCamera, Points, PointsMaterial, Scene, SphereGeometry, WebGLRenderer } from 'three'

const props = defineProps({ speaking: Boolean, listening: Boolean })
const canvas = ref()
const failed = ref(false)
let renderer, observer, raf
const geometries = []
const materials = []
let disposed = false

onMounted(() => {
  try {
    renderer = new WebGLRenderer({ canvas: canvas.value, alpha: true, antialias: true })
    renderer.setClearColor(0x000000, 0)
    const scene = new Scene()
    const camera = new PerspectiveCamera(38, 1, 0.1, 30)
    camera.position.z = 7
    const cloudGroup = new Group()
    const glintGroup = new Group()
    const orbGroup = new Group()
    scene.add(cloudGroup, glintGroup, orbGroup)
    const cloudMaterial = new PointsMaterial({ color: 0x6d28d9, size: .024, transparent: true, opacity: .68, depthWrite: false, blending: NormalBlending })
    const glintMaterial = new PointsMaterial({ color: 0x8b5cf6, size: .028, transparent: true, opacity: .65, depthWrite: false, blending: NormalBlending })
    const globeMaterial = new PointsMaterial({ color: 0x7c3aed, size: .018, transparent: true, opacity: .58, depthWrite: false, blending: NormalBlending })
    materials.push(cloudMaterial, glintMaterial, globeMaterial)

    const cloud = (samples, parent, pointMaterial) => {
      const positions = []
      samples.forEach(([x, y, z]) => positions.push(x, y, z))
      const geometry = new BufferGeometry()
      geometry.setAttribute('position', new Float32BufferAttribute(positions, 3))
      geometries.push(geometry)
      const points = new Points(geometry, pointMaterial)
      points.frustumCulled = false
      parent.add(points)
    }

    const fraction = value => value - Math.floor(value)
    const noise = (index, salt) => fraction(Math.sin(index * 127.1 + salt * 311.7) * 43758.5453)
    // Fill the surrounding 3D volume instead of tracing concentric rings.
    const particleVolume = (count, salt, minRadius, maxRadius) => {
      const samples = []
      for (let i = 0; i < count; i++) {
        const angle = noise(i, salt) * Math.PI * 2
        const y = noise(i, salt + 1.3) * 2 - 1
        const radial = Math.cbrt(noise(i, salt + 2.7) * (maxRadius ** 3 - minRadius ** 3) + minRadius ** 3)
        const planar = Math.sqrt(1 - y * y)
        const ripple = 1 + .055 * Math.sin(angle * 7 + y * 9 + salt)
        samples.push([Math.cos(angle) * planar * radial * ripple, y * radial * ripple, Math.sin(angle) * planar * radial * ripple])
      }
      return samples
    }
    cloud(particleVolume(2700, .17, .64, .84), cloudGroup, cloudMaterial)
    cloud(particleVolume(450, 4.39, .69, .9), glintGroup, glintMaterial)

    // Soft particle waves grow out of the same volume as the resting cloud.
    const ribbons = []
    for (let ribbonIndex = 0; ribbonIndex < 3; ribbonIndex++) {
      const group = new Group()
      const ribbonMaterial = new PointsMaterial({
        color: ribbonIndex === 1 ? 0xc4b5fd : 0x8b5cf6,
        size: .029, transparent: true, opacity: 0, depthWrite: false, blending: NormalBlending
      })
      const samples = []
      for (let i = 0; i < 1700; i++) {
        const angle = i * Math.PI * 2 / 1700 + (noise(i, ribbonIndex + 10.2) - .5) * .006
        const radius = 1 + (noise(i, ribbonIndex + 11.5) - .5) * .11
        const depth = (noise(i, ribbonIndex + 12.8) - .5) * .07
        samples.push([Math.cos(angle) * radius, Math.sin(angle) * radius, depth])
      }
      cloud(samples, group, ribbonMaterial)
      scene.add(group)
      materials.push(ribbonMaterial)
      ribbons.push({ group, material: ribbonMaterial })
    }

    const globeSamples = []
    for (let i = 0; i < 480; i++) {
      const y = 1 - 2 * (i + .5) / 480
      const angle = i * 2.39996323
      const radius = Math.sqrt(1 - y * y)
      globeSamples.push([Math.cos(angle) * radius * .62, y * .62, Math.sin(angle) * radius * .62])
    }
    const globeBaseGeometry = new SphereGeometry(.6, 32, 20)
    const globeBaseMaterial = new MeshBasicMaterial({ color: 0x6d28d9, transparent: true, opacity: .26, depthWrite: false })
    geometries.push(globeBaseGeometry)
    materials.push(globeBaseMaterial)
    const globeBase = new Mesh(globeBaseGeometry, globeBaseMaterial)
    globeBase.renderOrder = 0
    orbGroup.add(globeBase)
    const wireGeometry = new SphereGeometry(.625, 20, 14)
    const wireMaterial = new MeshBasicMaterial({ color: 0x7c3aed, wireframe: true, transparent: true, opacity: .24, depthWrite: false, blending: NormalBlending })
    geometries.push(wireGeometry)
    materials.push(wireMaterial)
    const wireframe = new Mesh(wireGeometry, wireMaterial)
    wireframe.renderOrder = 1
    orbGroup.add(wireframe)
    cloud(globeSamples, orbGroup, globeMaterial)
    const resize = () => {
      const { width, height } = canvas.value.getBoundingClientRect()
      if (!width || !height) return
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      renderer.setPixelRatio(ratio)
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
    observer = new ResizeObserver(resize)
    observer.observe(canvas.value)
    resize()
    let elapsed = 0, speakingTime = 0, wasSpeaking = false, energy = 0, previous = performance.now()
    const frame = now => {
      if (disposed) return
      raf = requestAnimationFrame(frame)
      const dt = Math.min((now - previous) / 1000, .05)
      previous = now
      if (document.hidden) return
      elapsed += dt
      const target = props.speaking ? 1 : props.listening ? .2 : 0
      const response = target > energy ? 2.2 : 1.7
      energy += (target - energy) * (1 - Math.exp(-dt * response))
      if (Math.abs(target - energy) < .001) energy = target
      if (props.speaking) {
        if (!wasSpeaking) speakingTime = 0
        speakingTime += dt
      }
      wasSpeaking = props.speaking
      const pulse = .5 + .5 * Math.sin(speakingTime * 4)
      cloudMaterial.size = .024 + energy * .002
      cloudMaterial.opacity = .58 + energy * .22
      glintMaterial.size = .028 + energy * .002
      glintMaterial.opacity = .5 + energy * .22
      ribbons.forEach(({ group, material }, index) => {
        const waveTime = speakingTime - index * .68
        const phase = waveTime > 0 ? (waveTime % 2.4) / 2.4 : 0
        group.scale.setScalar(.73 + phase * 1.4)
        group.rotation.z = speakingTime * (index % 2 ? -.07 : .08) + index * .35
        material.opacity = waveTime > 0 ? energy * .34 * Math.sin(Math.PI * phase) ** 1.3 : 0
        material.size = .029 + energy * .003
      })
      globeMaterial.opacity = .48 + energy * .48
      wireMaterial.opacity = .24 + energy * (.18 + pulse * .04)
      globeBaseMaterial.opacity = .26 + energy * .14
      cloudGroup.rotation.y += dt * energy * .13
      cloudGroup.rotation.x = energy * .2 * Math.sin(elapsed * .19)
      cloudGroup.rotation.z += dt * energy * .025
      glintGroup.rotation.y -= dt * energy * .09
      glintGroup.rotation.z -= dt * energy * .035
      cloudGroup.scale.setScalar(1 + energy * (1.5 + .008 * Math.sin(elapsed * 1.3)))
      glintGroup.scale.setScalar(1 + energy * 1.35)
      orbGroup.rotation.y += dt * energy * .31
      orbGroup.rotation.x = energy * .18 * Math.sin(elapsed * .23)
      orbGroup.scale.setScalar(1 + energy * (.015 + pulse * .02))
      renderer.render(scene, camera)
    }
    raf = requestAnimationFrame(frame)
  } catch {
    failed.value = true
  }
})
onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(raf)
  observer?.disconnect()
  geometries.forEach(geometry => geometry.dispose())
  materials.forEach(material => material.dispose())
  renderer?.dispose()
})
</script>

<template>
  <div class="particle-assistant" :class="{ speaking, listening }" role="img" :aria-label="speaking ? 'AI管家正在说话，粒子向外波动' : 'AI管家三维粒子球'">
    <div class="particle-aura" />
    <canvas v-show="!failed" ref="canvas" />
    <div v-if="failed" class="particle-fallback">全息助手已就绪</div>
    <div class="particle-core" />
  </div>
</template>

<style scoped>
.particle-assistant{position:absolute;inset:-16%;isolation:isolate;pointer-events:none;transition:inset .65s ease}
canvas{position:absolute;inset:0;width:100%;height:100%;z-index:2}
.particle-aura{position:absolute;inset:32%;border-radius:50%;background:radial-gradient(circle,#7c3aed20 9%,#8b5cf633 46%,#c4b5fd29 65%,transparent 78%);filter:blur(12px);transition:inset 1s ease,transform 1s ease,opacity 1s ease;opacity:.78}
.speaking .particle-aura{inset:12%;transform:scale(1.04);opacity:1;animation:aura 1.8s ease-in-out infinite alternate}
.particle-core{position:absolute;left:50%;top:50%;width:13%;height:13%;transform:translate(-50%,-50%);border-radius:50%;background:radial-gradient(circle,#ddd6fe87,#a78bfa4a 34%,#7c3aed15 67%,transparent 76%);filter:blur(11px);opacity:.45;transition:width .8s,height .8s,filter .8s,opacity .8s;z-index:1}
.speaking .particle-core{width:16%;height:16%;filter:blur(10px) brightness(1.45);opacity:1}
.particle-fallback{position:absolute;inset:28%;display:grid;place-items:center;border:1px solid #a78bfaa0;border-radius:50%;color:#6d28d9;font-size:14px;background:radial-gradient(circle,#7c3aed33,transparent 70%)}
@keyframes aura{to{transform:scale(1.1);opacity:.78}}
</style>
