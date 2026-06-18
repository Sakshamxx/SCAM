import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ClickSpark from './components/effects/ClickSpark'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ClickSpark
      sparkColor="#a78bfa"
      sparkSize={10}
      sparkRadius={15}
      sparkCount={8}
      duration={400}
      easing="ease-out"
      extraScale={1}
    >
      <App />
    </ClickSpark>
  </StrictMode>,
)
