import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import './CyberBackground.css';

export default function CyberBackground({ children }) {
  const containerRef = useRef(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [gridParticles, setGridParticles] = useState([]);

  // Initialize grid particles
  useEffect(() => {
    const particleCount = 200;
    const particles = Array.from({ length: particleCount }, (_, i) => ({
      id: i,
      x: Math.random() * 100,
      y: Math.random() * 100,
      size: Math.random() * 2 + 0.5,
      duration: Math.random() * 20 + 15,
      delay: Math.random() * 5,
      offsetX: Math.random() * 40 - 20,
      offsetY: Math.random() * 40 - 20,
    }));
    setGridParticles(particles);
  }, []);

  // Mouse tracking for parallax
  useEffect(() => {
    const handleMouseMove = (e) => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setMousePos({
          x: (e.clientX - rect.left) / rect.width,
          y: (e.clientY - rect.top) / rect.height,
        });
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  return (
    <div ref={containerRef} className="cyber-background">
      {/* Dark base background */}
      <div className="cyber-base" />

      {/* Primary gradient orb - purple center */}
      <motion.div
        className="cyber-orb cyber-orb-primary"
        animate={{
          x: mousePos.x * 40 - 20,
          y: mousePos.y * 40 - 20,
        }}
        transition={{ type: 'spring', damping: 30, mass: 0.5, stiffness: 100 }}
      />

      {/* Secondary floating orbs */}
      <motion.div
        className="cyber-orb cyber-orb-secondary"
        animate={{
          y: [0, 60, -40, 0],
          x: [0, -30, 30, 0],
        }}
        transition={{
          duration: 20,
          ease: 'easeInOut',
          repeat: Infinity,
        }}
      />

      <motion.div
        className="cyber-orb cyber-orb-tertiary"
        animate={{
          y: [0, -50, 40, 0],
          x: [0, 40, -20, 0],
        }}
        transition={{
          duration: 25,
          ease: 'easeInOut',
          repeat: Infinity,
          delay: 2,
        }}
      />

      {/* Curved digital grid */}
      <svg className="cyber-grid" viewBox="0 0 1200 800" preserveAspectRatio="none">
        <defs>
          <linearGradient id="gridGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#6339e4" stopOpacity="0.2" />
            <stop offset="50%" stopColor="#6339e4" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#6339e4" stopOpacity="0.1" />
          </linearGradient>
          <filter id="glow">
            <feGaussianBlur stdDeviation="2" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Horizontal curved lines */}
        {Array.from({ length: 12 }).map((_, i) => {
          const y = (i / 11) * 800;
          const offset = Math.sin((i / 11) * Math.PI) * 100;
          return (
            <motion.path
              key={`h-${i}`}
              d={`M -100 ${y} Q 600 ${y + offset} 1300 ${y}`}
              stroke="url(#gridGradient)"
              strokeWidth="1.5"
              fill="none"
              filter="url(#glow)"
              animate={{
                d: [
                  `M -100 ${y} Q 600 ${y + offset} 1300 ${y}`,
                  `M -100 ${y} Q 600 ${y + offset + 20} 1300 ${y}`,
                  `M -100 ${y} Q 600 ${y + offset} 1300 ${y}`,
                ],
              }}
              transition={{
                duration: 6 + i * 0.3,
                ease: 'easeInOut',
                repeat: Infinity,
              }}
            />
          );
        })}

        {/* Vertical curved lines */}
        {Array.from({ length: 10 }).map((_, i) => {
          const x = (i / 9) * 1200;
          const offset = Math.cos((i / 9) * Math.PI) * 80;
          return (
            <motion.path
              key={`v-${i}`}
              d={`M ${x} -100 Q ${x + offset} 400 ${x} 900`}
              stroke="url(#gridGradient)"
              strokeWidth="1.5"
              fill="none"
              filter="url(#glow)"
              animate={{
                d: [
                  `M ${x} -100 Q ${x + offset} 400 ${x} 900`,
                  `M ${x} -100 Q ${x + offset - 15} 400 ${x} 900`,
                  `M ${x} -100 Q ${x + offset} 400 ${x} 900`,
                ],
              }}
              transition={{
                duration: 7 + i * 0.4,
                ease: 'easeInOut',
                repeat: Infinity,
              }}
            />
          );
        })}
      </svg>

      {/* Matrix-style animated particles */}
      <div className="cyber-particles">
        {gridParticles.map((particle) => (
          <motion.div
            key={particle.id}
            className="cyber-particle"
            style={{
              width: particle.size,
              height: particle.size,
              left: `${particle.x}%`,
              top: `${particle.y}%`,
            }}
            animate={{
              y: [0, particle.offsetY, 0],
              x: [0, particle.offsetX, 0],
              opacity: [0, 0.8, 0],
            }}
            transition={{
              duration: particle.duration,
              delay: particle.delay,
              ease: 'easeInOut',
              repeat: Infinity,
            }}
          />
        ))}
      </div>

      {/* Pulsing accent glows */}
      <motion.div
        className="cyber-pulse-glow"
        animate={{
          opacity: [0.3, 0.6, 0.3],
          scale: [1, 1.1, 1],
        }}
        transition={{
          duration: 4,
          ease: 'easeInOut',
          repeat: Infinity,
        }}
      />

      <motion.div
        className="cyber-pulse-glow cyber-pulse-glow-secondary"
        animate={{
          opacity: [0.2, 0.5, 0.2],
          scale: [1, 0.9, 1],
        }}
        transition={{
          duration: 5,
          ease: 'easeInOut',
          repeat: Infinity,
          delay: 1,
        }}
      />

      {/* Content container with higher z-index */}
      <div className="cyber-content">{children}</div>
    </div>
  );
}
