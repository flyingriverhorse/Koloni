import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { takeKey } from './api/client'
// The faces come with the app (KOLONİ works offline too): only the weights the stylesheets use.
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './theme/tokens.css'
import './theme/base.css'
import './theme/canvas.css'
import './theme/changes.css'
import './theme/commands.css'
import './theme/memory.css'
import './theme/triggers.css'
import './theme/usage.css'
import './theme/board.css'

// A new link pasted into this tab changes only the hash: the page starts again, with its key.
window.addEventListener('hashchange', () => {
  if (new URLSearchParams(location.hash.slice(1)).has('key')) location.reload()
})
// (Drawn once the key is in hand: a `#open=` code is exchanged for it first. Without one, the page says how to get it.)
void takeKey()
  .catch(() => {})
  .then(() =>
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    ),
  )
