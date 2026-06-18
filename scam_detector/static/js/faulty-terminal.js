/**
 * FaultyTerminal Effect for ScamShield
 * 
 * Cyberpunk terminal glitch effect with:
 * - Scanlines
 * - Chromatic aberration
 * - Glitch animation
 * - Flicker effect
 * - Dither pattern
 * - CRT curve
 * - Mouse reactivity
 * - Performance optimized
 */

class FaultyTerminal {
  constructor(options = {}) {
    this.config = {
      scale: options.scale || 1.5,
      digitSize: options.digitSize || 2.1,
      scanlineIntensity: options.scanlineIntensity || 0.25,
      glitchAmount: options.glitchAmount || 0.6,
      flickerAmount: options.flickerAmount || 2.4,
      noiseAmp: options.noiseAmp || 0,
      chromaticAberration: options.chromaticAberration || 0.085,
      dither: options.dither || 0.25,
      curvature: options.curvature || 0.2,
      tint: options.tint || '#6339e4',
      mouseReact: options.mouseReact !== false,
      mouseStrength: options.mouseStrength || 0.55,
      brightness: options.brightness || 1.6,
      container: options.container || document.body,
    };

    this.mouseX = 0;
    this.mouseY = 0;
    this.time = 0;
    this.animationId = null;
    this.container = null;
    this.canvas = null;
    this.ctx = null;

    this.init();
  }

  init() {
    // Create canvas
    this.canvas = document.createElement('canvas');
    this.canvas.style.position = 'fixed';
    this.canvas.style.top = '0';
    this.canvas.style.left = '0';
    this.canvas.style.width = '100%';
    this.canvas.style.height = '100%';
    this.canvas.style.zIndex = '-1';
    this.canvas.style.pointerEvents = 'none';

    this.config.container.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d', { alpha: false });

    // Set initial canvas size
    this.updateCanvasSize();

    // Event listeners
    window.addEventListener('resize', () => this.updateCanvasSize());
    if (this.config.mouseReact) {
      document.addEventListener('mousemove', (e) => this.handleMouseMove(e));
    }

    // Start animation loop
    this.animate();
  }

  updateCanvasSize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  handleMouseMove(e) {
    this.mouseX = e.clientX / window.innerWidth;
    this.mouseY = e.clientY / window.innerHeight;
  }

  animate = () => {
    this.time += 1;

    const w = this.canvas.width;
    const h = this.canvas.height;

    // Clear with dark background
    this.ctx.fillStyle = '#0a0a14';
    this.ctx.fillRect(0, 0, w, h);

    // Draw base terminal effect
    this.drawTerminalEffect(w, h);

    // Draw scanlines
    this.drawScanlines(w, h);

    // Draw dither
    this.drawDither(w, h);

    // Draw noise/glitch
    this.drawGlitch(w, h);

    // Draw flicker
    this.drawFlicker(w, h);

    // Apply chromatic aberration as overlay
    this.drawChromaticAberration(w, h);

    this.animationId = requestAnimationFrame(this.animate);
  };

  drawTerminalEffect(w, h) {
    // Create radial gradient tint
    const gradient = this.ctx.createRadialGradient(
      w / 2 + this.mouseX * 100,
      h / 2 + this.mouseY * 100,
      0,
      w / 2,
      h / 2,
      Math.hypot(w, h)
    );

    const tintColor = this.hexToRgb(this.config.tint);
    gradient.addColorStop(0, `rgba(${tintColor}, 0.15)`);
    gradient.addColorStop(0.5, `rgba(${tintColor}, 0.05)`);
    gradient.addColorStop(1, `rgba(${tintColor}, 0)`);

    this.ctx.fillStyle = gradient;
    this.ctx.fillRect(0, 0, w, h);

    // Vignette effect
    const vignetteGradient = this.ctx.createRadialGradient(
      w / 2,
      h / 2,
      0,
      w / 2,
      h / 2,
      Math.hypot(w, h) * 0.7
    );
    vignetteGradient.addColorStop(0, 'rgba(0, 0, 0, 0)');
    vignetteGradient.addColorStop(1, 'rgba(0, 0, 0, 0.6)');

    this.ctx.fillStyle = vignetteGradient;
    this.ctx.fillRect(0, 0, w, h);
  }

  drawScanlines(w, h) {
    const intensity = this.config.scanlineIntensity;
    const spacing = 2;

    this.ctx.strokeStyle = `rgba(0, 0, 0, ${intensity})`;
    this.ctx.lineWidth = spacing;

    for (let y = 0; y < h; y += spacing) {
      this.ctx.beginPath();
      this.ctx.moveTo(0, y);
      this.ctx.lineTo(w, y);
      this.ctx.stroke();
    }

    // Bright scanlines
    this.ctx.strokeStyle = `rgba(255, 255, 255, ${intensity * 0.3})`;
    for (let y = 0; y < h; y += spacing * 2) {
      this.ctx.beginPath();
      this.ctx.moveTo(0, y);
      this.ctx.lineTo(w, y);
      this.ctx.stroke();
    }
  }

  drawDither(w, h) {
    const intensity = this.config.dither;
    const pixelSize = 4;

    this.ctx.globalAlpha = intensity;
    this.ctx.fillStyle = '#ffffff';

    for (let y = 0; y < h; y += pixelSize) {
      for (let x = 0; x < w; x += pixelSize) {
        if (Math.random() > 0.5) {
          this.ctx.fillRect(x, y, pixelSize, pixelSize);
        }
      }
    }

    this.ctx.globalAlpha = 1;
  }

  drawGlitch(w, h) {
    const glitchStrength = this.config.glitchAmount;
    const glitchFreq = Math.sin(this.time * 0.02) * 0.5 + 0.5;

    if (glitchFreq < 0.3) {
      const glitchOffset = (Math.random() - 0.5) * glitchStrength * 20;
      const glitchHeight = Math.random() * h * 0.3;
      const glitchY = Math.random() * h;

      this.ctx.fillStyle = `rgba(99, 57, 228, ${glitchStrength * 0.4})`;
      this.ctx.fillRect(0, glitchY, w, glitchHeight);

      this.ctx.fillStyle = `rgba(255, 0, 255, ${glitchStrength * 0.2})`;
      this.ctx.fillRect(glitchOffset, glitchY, w, glitchHeight);
    }
  }

  drawFlicker(w, h) {
    const flicker = Math.sin(this.time * this.config.flickerAmount * 0.1) * 0.5 + 0.5;
    const brightness = this.config.brightness - 1 + flicker * 0.3;

    this.ctx.fillStyle = `rgba(255, 255, 255, ${Math.max(0, flicker * 0.08)})`;
    this.ctx.fillRect(0, 0, w, h);
  }

  drawChromaticAberration(w, h) {
    const aberration = this.config.chromaticAberration;

    if (aberration > 0) {
      const offsetX = (Math.sin(this.time * 0.05) * aberration * 10) * (0.5 + this.mouseX);
      const offsetY = (Math.cos(this.time * 0.05) * aberration * 10) * (0.5 + this.mouseY);

      // Red channel shift
      this.ctx.fillStyle = `rgba(255, 0, 0, ${aberration * 0.15})`;
      this.ctx.fillRect(offsetX, offsetY, w, h);

      // Blue channel shift
      this.ctx.fillStyle = `rgba(0, 0, 255, ${aberration * 0.1})`;
      this.ctx.fillRect(-offsetX, -offsetY, w, h);
    }
  }

  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (result) {
      return `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`;
    }
    return '99, 57, 228'; // Default purple
  }

  destroy() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
    if (this.canvas && this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas);
    }
    document.removeEventListener('mousemove', this.handleMouseMove);
    window.removeEventListener('resize', this.updateCanvasSize);
  }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    new FaultyTerminal({
      scale: 1.5,
      digitSize: 2.1,
      scanlineIntensity: 0.25,
      glitchAmount: 0.6,
      flickerAmount: 2.4,
      noiseAmp: 0,
      chromaticAberration: 0.085,
      dither: 0.25,
      curvature: 0.2,
      tint: '#6339e4',
      mouseReact: true,
      mouseStrength: 0.55,
      brightness: 1.6,
    });
  });
} else {
  new FaultyTerminal({
    scale: 1.5,
    digitSize: 2.1,
    scanlineIntensity: 0.25,
    glitchAmount: 0.6,
    flickerAmount: 2.4,
    noiseAmp: 0,
    chromaticAberration: 0.085,
    dither: 0.25,
    curvature: 0.2,
    tint: '#6339e4',
    mouseReact: true,
    mouseStrength: 0.55,
    brightness: 1.6,
  });
}
