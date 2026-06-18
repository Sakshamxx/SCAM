import React, { useRef, useEffect, useCallback } from 'react';

/**
 * ClickSpark Component
 * 
 * Creates animated spark particles on click with configurable properties.
 * Uses Canvas for optimal performance with requestAnimationFrame.
 * 
 * @param {Object} props
 * @param {string} props.sparkColor - Color of the spark particles (default: "#a78bfa")
 * @param {number} props.sparkSize - Size of each spark particle in pixels (default: 10)
 * @param {number} props.sparkRadius - Radius of the spark explosion area (default: 15)
 * @param {number} props.sparkCount - Number of spark particles per click (default: 8)
 * @param {number} props.duration - Animation duration in milliseconds (default: 400)
 * @param {string} props.easing - Easing function name (default: "ease-out")
 * @param {number} props.extraScale - Extra scale multiplier (default: 1)
 * @param {React.ReactNode} props.children - Child components to wrap
 */
const ClickSpark = ({
  sparkColor = '#a78bfa',
  sparkSize = 10,
  sparkRadius = 15,
  sparkCount = 8,
  duration = 400,
  easing = 'ease-out',
  extraScale = 1,
  children,
}) => {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const particlesRef = useRef([]);
  const animationIdRef = useRef(null);

  // Easing function implementations
  const easingFunctions = {
    'ease-out': (t) => 1 - Math.pow(1 - t, 3),
    'ease-in': (t) => t * t * t,
    'ease-in-out': (t) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
    'linear': (t) => t,
  };

  const getEasingFunction = (easingName) => {
    return easingFunctions[easingName] || easingFunctions['ease-out'];
  };

  // Initialize canvas when container mounts
  useEffect(() => {
    if (!containerRef.current) return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = containerRef.current.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;

    // Handle window resize
    const handleResize = () => {
      if (!containerRef.current) return;
      const newRect = containerRef.current.getBoundingClientRect();
      canvas.width = newRect.width;
      canvas.height = newRect.height;
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Create particles at click position
  const createParticles = useCallback((x, y) => {
    const angle = (Math.PI * 2) / sparkCount;
    const startTime = Date.now();

    for (let i = 0; i < sparkCount; i++) {
      const direction = angle * i + (Math.random() - 0.5) * 0.5;
      const velocity = 2 + Math.random() * 2;

      const particle = {
        x,
        y,
        vx: Math.cos(direction) * velocity,
        vy: Math.sin(direction) * velocity,
        life: 1,
        startTime,
        size: sparkSize * (0.5 + Math.random() * 0.5),
      };

      particlesRef.current.push(particle);
    }
  }, [sparkSize, sparkCount]);

  // Animation loop using Canvas
  const animate = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const currentTime = Date.now();

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Update and draw particles
    const easingFn = getEasingFunction(easing);
    const particlesToRemove = [];

    particlesRef.current.forEach((particle, index) => {
      const elapsed = currentTime - particle.startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      // Easing applied to life
      particle.life = 1 - progress;

      // Update position with gravity
      particle.x += particle.vx * extraScale;
      particle.y += particle.vy * extraScale + 0.1; // gravity
      particle.vy *= 0.98; // air resistance

      // Apply easing to opacity
      const opacity = particle.life * easingFn(1 - progress);

      if (opacity > 0.01) {
        // Draw particle
        ctx.fillStyle = `${sparkColor}${Math.round(opacity * 255).toString(16).padStart(2, '0')}`;
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
        ctx.fill();
      }

      // Mark for removal if animation complete
      if (progress >= 1) {
        particlesToRemove.push(index);
      }
    });

    // Remove completed particles
    particlesToRemove.reverse().forEach((index) => {
      particlesRef.current.splice(index, 1);
    });

    // Continue animation if particles exist
    if (particlesRef.current.length > 0) {
      animationIdRef.current = requestAnimationFrame(animate);
    } else {
      animationIdRef.current = null;
    }
  }, [duration, easing, sparkColor, extraScale]);

  // Handle click events
  const handleClick = useCallback((event) => {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    createParticles(x, y);

    // Start animation if not already running
    if (!animationIdRef.current) {
      animationIdRef.current = requestAnimationFrame(animate);
    }
  }, [createParticles, animate]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (animationIdRef.current) {
        cancelAnimationFrame(animationIdRef.current);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      onClick={handleClick}
      style={{ position: 'relative', width: '100%', height: '100%' }}
    >
      <canvas
        ref={canvasRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          pointerEvents: 'none',
          zIndex: 9999,
        }}
      />
      {children}
    </div>
  );
};

export default ClickSpark;
