/**
 * Premium SaaS Background Effect
 * 
 * Modern cybersecurity authentication background with:
 * - Floating gradient blobs
 * - Smooth mouse tracking
 * - Glassmorphism design
 * - Particle sparkles
 * - Responsive animations
 * - Zero glitch effects or CRT noise
 */

class PremiumSaaSBackground {
  constructor(options = {}) {
    this.config = {
      primaryColor: options.primaryColor || '#6366f1',
      secondaryColor: options.secondaryColor || '#8b5cf6',
      backgroundColor: options.backgroundColor || '#0f172a',
      accentColor: options.accentColor || '#a5b4fc',
      particleCount: options.particleCount || 50,
      container: options.container || document.body,
    };

    this.mouseX = 0;
    this.mouseY = 0;
    this.time = 0;
    this.animationId = null;
    this.canvas = null;
    this.ctx = null;
    this.particles = [];
    this.blobs = [];

    this.init();
  }

  init() {
    // Create canvas for animations
    this.canvas = document.createElement('canvas');
    this.canvas.style.position = 'fixed';
    this.canvas.style.top = '0';
    this.canvas.style.left = '0';
    this.canvas.style.width = '100%';
    this.canvas.style.height = '100%';
    this.canvas.style.zIndex = '1';
    this.canvas.style.pointerEvents = 'none';
    this.canvas.style.backgroundColor = this.config.backgroundColor;

    this.config.container.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d', { alpha: true });

    // Initialize particles
    this.initializeParticles();

    // Initialize blobs
    this.initializeBlobs();

    // Update canvas size
    this.updateCanvasSize();

    // Event listeners
    window.addEventListener('resize', () => this.updateCanvasSize());
    document.addEventListener('mousemove', (e) => this.handleMouseMove(e));

    // Start animation loop
    this.animate();
  }

  initializeParticles() {
    this.particles = [];
    for (let i = 0; i < this.config.particleCount; i++) {
      this.particles.push({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        vx: (Math.random() - 0.5) * 1.5,
        vy: (Math.random() - 0.5) * 1.5,
        size: Math.random() * 1.5 + 0.5,
        opacity: Math.random() * 0.5 + 0.3,
        life: Math.random() * 200 + 100,
        maxLife: Math.random() * 200 + 100,
      });
    }
  }

  initializeBlobs() {
    this.blobs = [
      {
        x: window.innerWidth * 0.2,
        y: window.innerHeight * 0.3,
        vx: 0.3,
        vy: 0.2,
        size: 300,
        color: this.config.primaryColor,
        phase: 0,
      },
      {
        x: window.innerWidth * 0.8,
        y: window.innerHeight * 0.7,
        vx: -0.25,
        vy: -0.3,
        size: 250,
        color: this.config.secondaryColor,
        phase: Math.PI * 0.67,
      },
      {
        x: window.innerWidth * 0.5,
        y: window.innerHeight * 0.5,
        vx: 0.2,
        vy: -0.15,
        size: 200,
        color: this.config.primaryColor,
        phase: Math.PI * 1.33,
      },
    ];
  }

  updateCanvasSize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  handleMouseMove(e) {
    this.mouseX = e.clientX;
    this.mouseY = e.clientY;
  }

  animate = () => {
    this.time += 0.016; // 60fps delta

    const w = this.canvas.width;
    const h = this.canvas.height;

    // Clear canvas
    this.ctx.fillStyle = this.config.backgroundColor;
    this.ctx.fillRect(0, 0, w, h);

    // Draw blobs
    this.drawBlobs(w, h);

    // Draw mouse glow
    this.drawMouseGlow(w, h);

    // Update and draw particles
    this.updateParticles();
    this.drawParticles();

    // Draw vignette
    this.drawVignette(w, h);

    this.animationId = requestAnimationFrame(this.animate);
  };

  drawBlobs(w, h) {
    this.blobs.forEach((blob) => {
      // Smooth floating motion
      blob.x += Math.sin(this.time * 0.5 + blob.phase) * 0.5;
      blob.y += Math.cos(this.time * 0.4 + blob.phase) * 0.5;

      // Boundary wrapping with smooth transition
      if (blob.x < -blob.size) blob.x = w + blob.size;
      if (blob.x > w + blob.size) blob.x = -blob.size;
      if (blob.y < -blob.size) blob.y = h + blob.size;
      if (blob.y > h + blob.size) blob.y = -blob.size;

      // Draw blob with gradient
      const gradient = this.ctx.createRadialGradient(
        blob.x,
        blob.y,
        0,
        blob.x,
        blob.y,
        blob.size
      );

      const color = this.hexToRgb(blob.color);
      gradient.addColorStop(0, `rgba(${color}, 0.6)`);
      gradient.addColorStop(0.5, `rgba(${color}, 0.2)`);
      gradient.addColorStop(1, `rgba(${color}, 0)`);

      this.ctx.globalCompositeOperation = 'screen';
      this.ctx.fillStyle = gradient;
      this.ctx.beginPath();
      this.ctx.arc(blob.x, blob.y, blob.size, 0, Math.PI * 2);
      this.ctx.fill();
      this.ctx.globalCompositeOperation = 'source-over';
    });
  }

  drawMouseGlow(w, h) {
    const glowSize = 300;
    const gradient = this.ctx.createRadialGradient(
      this.mouseX,
      this.mouseY,
      0,
      this.mouseX,
      this.mouseY,
      glowSize
    );

    gradient.addColorStop(0, `rgba(163, 230, 253, 0.15)`);
    gradient.addColorStop(0.5, `rgba(139, 92, 246, 0.05)`);
    gradient.addColorStop(1, `rgba(139, 92, 246, 0)`);

    this.ctx.globalCompositeOperation = 'screen';
    this.ctx.fillStyle = gradient;
    this.ctx.fillRect(
      this.mouseX - glowSize,
      this.mouseY - glowSize,
      glowSize * 2,
      glowSize * 2
    );
    this.ctx.globalCompositeOperation = 'source-over';
  }

  updateParticles() {
    this.particles.forEach((particle) => {
      particle.x += particle.vx;
      particle.y += particle.vy;

      // Gravity-like effect
      particle.vy += 0.1;

      // Boundary wrapping
      if (particle.x < 0) particle.x = this.canvas.width;
      if (particle.x > this.canvas.width) particle.x = 0;
      if (particle.y > this.canvas.height) {
        particle.y = 0;
        particle.x = Math.random() * this.canvas.width;
      }

      // Fade in/out
      particle.life -= 1;
      if (particle.life <= 0) {
        particle.life = particle.maxLife;
        particle.y = 0;
        particle.x = Math.random() * this.canvas.width;
        particle.vx = (Math.random() - 0.5) * 1.5;
        particle.vy = (Math.random() - 0.5) * 1.5;
      }

      particle.opacity = (particle.life / particle.maxLife) * 0.6;
    });
  }

  drawParticles() {
    this.particles.forEach((particle) => {
      this.ctx.globalAlpha = particle.opacity;
      this.ctx.fillStyle = this.config.accentColor;

      // Draw particle with subtle glow
      const gradient = this.ctx.createRadialGradient(
        particle.x,
        particle.y,
        0,
        particle.x,
        particle.y,
        particle.size * 2
      );
      gradient.addColorStop(0, this.config.accentColor);
      gradient.addColorStop(1, `rgba(165, 180, 252, 0)`);

      this.ctx.fillStyle = gradient;
      this.ctx.beginPath();
      this.ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
      this.ctx.fill();
    });

    this.ctx.globalAlpha = 1;
  }

  drawVignette(w, h) {
    const gradient = this.ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.7);

    gradient.addColorStop(0, 'rgba(0, 0, 0, 0)');
    gradient.addColorStop(1, `rgba(15, 23, 42, 0.4)`);

    this.ctx.fillStyle = gradient;
    this.ctx.fillRect(0, 0, w, h);
  }

  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (result) {
      return `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`;
    }
    return '99, 102, 241';
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

// Initialize on page load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    new PremiumSaaSBackground({
      primaryColor: '#6366f1',
      secondaryColor: '#8b5cf6',
      backgroundColor: '#0f172a',
      accentColor: '#a5b4fc',
      particleCount: 50,
    });
  });
} else {
  new PremiumSaaSBackground({
    primaryColor: '#6366f1',
    secondaryColor: '#8b5cf6',
    backgroundColor: '#0f172a',
    accentColor: '#a5b4fc',
    particleCount: 50,
  });
}
