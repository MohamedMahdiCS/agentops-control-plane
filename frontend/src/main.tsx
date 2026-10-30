import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource-variable/space-grotesk'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import App from './App.tsx'
import { OperatorProvider } from './operator'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <OperatorProvider>
      <App />
    </OperatorProvider>
  </StrictMode>,
)
