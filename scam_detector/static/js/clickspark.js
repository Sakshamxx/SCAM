/**
 * ClickSpark Effect for ScamShield
 * 
 * Premium spark burst effect with:
 * - Thin spark streaks (not circles)
 * - Purple/white glow
 * - Radial burst animation
 * - High performance (requestAnimationFrame)
 * - Memory safe (auto cleanup)
 */

class ClickSpark {
  constructor(options = {}) {
    this.config = {
      sparkColor: options.sparkColor || '#ffffff',
      glowColor: options.glowColor || '#a78bfa',
      particleCount: options.particleCount || 8,
      duration: options.duration || 350,
      minVelocity: options.minVelocity || 3,
      maxVelocity: options.maxVelocity || 7,
      gravity: options.gravity || 0.15,
      friction: options.friction || 0.98,
      sparkLength: options.sparkLength || 20,
      strokeWidth: options.strokeWidth || 1.5,
      ...options
    };

    this.particles = [];
    this.canvas = null;
    this.ctx = null;
    this.animationId = null;
    this.lastParticleTime = 0;
    this.particleDebounce = 50; // ms between particle bursts

    this.init();
  }

  init() {
    // Create canvas
    this.canvas = document.createElement('canvas');
    this.canvas.style.position = 'fixed';
    this.canvas.style.top = '0';
    this.canvas.style.left = '0';
    this.canvas.style.pointerEvents = 'none';
    this.canvas.style.zIndex = '9999';
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;

    document.body.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');

    // Set up event listeners
    document.addEventListener('click', (e) => this.createBurst(e));
    window.addEventListener('resize', () => this.handleResize());

    // Start animation loop
    this.animate();
  }

  createBurst(event) {
    // Debounce rapid clicks
    const now = Date.now();
    if (now - this.lastParticleTime < this.particleDebounce) return;
    this.lastParticleTime = now;

    const x = event.clientX;
    const y = event.clientY;
    const angle = (Math.PI * 2) / this.config.particleCount;

    for (let i = 0; i < this.config.particleCount; i++) {
      const direction = angle * i + (Math.random() - 0.5) * 0.4;
      const velocity = this.config.minVelocity + 
                       Math.random() * (this.config.maxVelocity - this.config.minVelocity);

      const particle = {
        x: x,
        y: y,
        vx: Math.cos(direction) * velocity,
        vy: Math.sin(direction) * velocity,
        age: 0,
        maxAge: this.config.duration,
        startTime: Date.now(),
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.05,
        length: this.config.sparkLength * (0.6 + Math.random() * 0.4),
        opacity: 1,
      };

      this.particles.push(particle);
    }
  }

  animate = () => {
    // Clear canvas
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    const now = Date.now();
    const particlesToRemove = [];

    // Update and draw particles
    this.particles.forEach((particle, index) => {
      const elapsed = now - particle.startTime;
      const progress = Math.min(elapsed / particle.maxAge, 1);

      // Physics
      particle.vx *= this.config.friction;
      particle.vy *= this.config.friction;
      particle.vy += this.config.gravity;

      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.rotation += particle.rotationSpeed;

      // Easing: ease-out
      const easeOut = 1 - Math.pow(1 - progress, 3);
      particle.opacity = Math.max(0, 1 - easeOut);

      // Draw spark streak
      if (particle.opacity > 0.01) {
        this.drawSpark(particle);
      }

      // Mark for removal
      if (progress >= 1) {
        particlesToRemove.push(index);
      }
    });

    // Remove dead particles
    particlesToRemove.reverse().forEach(idx => {
      this.particles.splice(idx, 1);
    });

    // Continue animation
    this.animationId = requestAnimationFrame(this.animate);
  };

  drawSpark(particle) {
    const { x, y, rotation, length, opacity } = particle;

    // Save context
    this.ctx.save();

    // Translate and rotate
    this.ctx.translate(x, y);
    this.ctx.rotate(rotation);

    // Draw glow (outer)
    this.ctx.strokeStyle = `rgba(${this.hexToRgb(this.config.glowColor)}, ${opacity * 0.6})`;
    this.ctx.lineWidth = this.config.strokeWidth * 3;
    this.ctx.lineCap = 'round';
    this.ctx.globalAlpha = opacity * 0.4;
    this.ctx.beginPath();
    this.ctx.moveTo(-length / 2, 0);
    this.ctx.lineTo(length / 2, 0);
    this.ctx.stroke();

    // Draw main spark (bright)
    this.ctx.strokeStyle = `rgba(${this.hexToRgb(this.config.sparkColor)}, ${opacity})`;
    this.ctx.lineWidth = this.config.strokeWidth;
    this.ctx.globalAlpha = opacity;
    this.ctx.beginPath();
    this.ctx.moveTo(-length / 2, 0);
    this.ctx.lineTo(length / 2, 0);
    this.ctx.stroke();

    // Core glow (ultra bright center)
    this.ctx.strokeStyle = `rgba(255, 255, 255, ${opacity * 0.8})`;
    this.ctx.lineWidth = this.config.strokeWidth * 0.6;
    this.ctx.globalAlpha = opacity;
    this.ctx.beginPath();
    this.ctx.moveTo(-length / 3, 0);
    this.ctx.lineTo(length / 3, 0);
    this.ctx.stroke();

    this.ctx.restore();
  }

  hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (result) {
      return `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`;
    }
    return '255, 255, 255';
  }

  handleResize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  destroy() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
    if (this.canvas && this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas);
    }
    document.removeEventListener('click', this.createBurst);
    window.removeEventListener('resize', this.handleResize);
  }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    new ClickSpark({
      sparkColor: '#ffffff',
      glowColor: '#a78bfa',
      particleCount: 8,
      duration: 350,
      minVelocity: 3,
      maxVelocity: 7,
      gravity: 0.15,
      friction: 0.98,
      sparkLength: 20,
      strokeWidth: 1.5,
    });
  });
} else {
  new ClickSpark({
    sparkColor: '#ffffff',
    glowColor: '#a78bfa',
    particleCount: 8,
    duration: 350,
    minVelocity: 3,
    maxVelocity: 7,
    gravity: 0.15,
    friction: 0.98,
    sparkLength: 20,
    strokeWidth: 1.5,
  });
}
