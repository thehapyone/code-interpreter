import { useEffect, useMemo, useState } from 'react'
import './App.css'
import type { ExecResponse, HealthResponse, RuntimeCapabilities, SessionFile, UploadResponse } from './types'

const STORAGE_KEY = 'mcp-ui-config'
const DEFAULT_LANG = 'py'

const LANGUAGES = [
  { value: 'py', label: 'Python (stateful + streaming)' },
  { value: 'bash', label: 'Bash' },
  { value: 'js', label: 'Node.js' },
  { value: 'ts', label: 'TypeScript (ts-node)' },
  { value: 'go', label: 'Go' },
  { value: 'cpp', label: 'C++' },
]

type ConfigState = {
  baseUrl: string
  apiKey: string
  entityId: string
}

const emptyConfig: ConfigState = {
  baseUrl: 'http://localhost:8000',
  apiKey: '',
  entityId: 'dev_agent',
}

function loadConfig(): ConfigState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      return { ...emptyConfig, ...JSON.parse(stored) }
    }
  } catch (err) {
    console.error('Failed to parse stored config', err)
  }
  return emptyConfig
}

function saveConfig(config: ConfigState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}

function buildHeaders(apiKey: string, isJson = true): HeadersInit {
  const headers: HeadersInit = {}
  if (isJson) {
    headers['Content-Type'] = 'application/json'
  }
  if (apiKey) {
    headers['x-api-key'] = apiKey
  }
  return headers
}

function App() {
  const [config, setConfig] = useState<ConfigState>(() => loadConfig())
  const [language, setLanguage] = useState(DEFAULT_LANG)
  const [code, setCode] = useState('print("Hello from MCP UI")')
  const [args, setArgs] = useState('')
  const [selectedFiles, setSelectedFiles] = useState<FileList | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionFiles, setSessionFiles] = useState<SessionFile[]>([])
  const [health, setHealth] = useState<RuntimeCapabilities | null>(null)
  const [healthStatus, setHealthStatus] = useState('idle')
  const [uploadStatus, setUploadStatus] = useState<string>('')
  const [execResult, setExecResult] = useState<ExecResponse | null>(null)
  const [execStatus, setExecStatus] = useState<string>('idle')
  const [streamLog, setStreamLog] = useState('')
  const [streaming, setStreaming] = useState(false)

  useEffect(() => {
    saveConfig(config)
  }, [config])

  const availableRuntimes = useMemo(() => {
    if (!health) return []
    return Object.entries(health).map(([name, data]) => ({
      name,
      available: data.available,
      missing: data.missing,
    }))
  }, [health])

  const fetchHealth = async () => {
    try {
      setHealthStatus('loading')
      const res = await fetch(`${config.baseUrl}/health`, {
        headers: buildHeaders(config.apiKey, false),
      })
      if (!res.ok) {
        throw new Error(await res.text())
      }
      const payload: HealthResponse = await res.json()
      setHealth(payload.runtime_capabilities ?? null)
      setHealthStatus('success')
    } catch (error) {
      console.error(error)
      setHealth(null)
      setHealthStatus('error')
    }
  }

  useEffect(() => {
    fetchHealth()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refreshFiles = async (id = sessionId) => {
    if (!id) return
    try {
      const res = await fetch(`${config.baseUrl}/files/${id}?detail=full`, {
        headers: buildHeaders(config.apiKey, false),
      })
      if (!res.ok) {
        throw new Error(await res.text())
      }
      const files = (await res.json()) as SessionFile[]
      setSessionFiles(files)
    } catch (error) {
      console.error('Failed to fetch files', error)
    }
  }

  const handleUpload = async () => {
    if (!selectedFiles || selectedFiles.length === 0) {
      setUploadStatus('Select files first')
      return
    }
    try {
      setUploadStatus('Uploading…')
      const form = new FormData()
      form.append('entity_id', config.entityId)
      Array.from(selectedFiles).forEach((file) => {
        form.append('files', file)
      })

      const res = await fetch(`${config.baseUrl}/upload`, {
        method: 'POST',
        headers: buildHeaders(config.apiKey, false),
        body: form,
      })

      if (!res.ok) {
        throw new Error(await res.text())
      }

      const payload = (await res.json()) as UploadResponse
      setSessionId(payload.session_id)
      setSessionFiles(payload.files)
      setUploadStatus(`Uploaded to session ${payload.session_id}`)
    } catch (error) {
      console.error(error)
      setUploadStatus('Upload failed – see console')
    }
  }

  const handleExec = async () => {
    if (!code.trim()) {
      setExecStatus('Enter some code first')
      return
    }
    try {
      setExecStatus('Running…')
      const payload: Record<string, unknown> = {
        code,
        lang: language,
        entity_id: config.entityId,
      }
      if (args.trim()) {
        payload.args = args.trim()
      }
      if (sessionFiles.length > 0) {
        payload.files = sessionFiles.map((file) => ({
          id: file.id,
          session_id: file.session_id,
          name: file.name,
        }))
      }

      const res = await fetch(`${config.baseUrl}/exec`, {
        method: 'POST',
        headers: buildHeaders(config.apiKey),
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        throw new Error(await res.text())
      }

      const body = (await res.json()) as ExecResponse
      setExecResult(body)
      setSessionId(body.session_id)
      setExecStatus('Success')
      await refreshFiles(body.session_id)
    } catch (error) {
      console.error(error)
      setExecStatus('Execution failed – see console')
    }
  }

  const handleStream = async () => {
    if (language !== 'py') {
      setExecStatus('Streaming is Python-only')
      return
    }
    try {
      setStreaming(true)
      setStreamLog('')
      const payload: Record<string, unknown> = {
        code,
        lang: 'py',
        entity_id: config.entityId,
      }
      if (args.trim()) {
        payload.args = args.trim()
      }
      if (sessionFiles.length > 0) {
        payload.files = sessionFiles.map((file) => ({
          id: file.id,
          session_id: file.session_id,
          name: file.name,
        }))
      }

      const res = await fetch(`${config.baseUrl}/exec/stream`, {
        method: 'POST',
        headers: buildHeaders(config.apiKey),
        body: JSON.stringify(payload),
      })

      if (!res.ok || !res.body) {
        throw new Error(await res.text())
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let done = false
      while (!done) {
        const chunk = await reader.read()
        done = chunk.done ?? false
        if (chunk.value) {
          setStreamLog((prev) => prev + decoder.decode(chunk.value))
        }
      }
      await refreshFiles()
    } catch (error) {
      console.error(error)
      setStreamLog((prev) => prev + '\n[stream error – see console]')
    } finally {
      setStreaming(false)
    }
  }

  const downloadFile = async (file: SessionFile) => {
    if (!sessionId) return
    try {
      const res = await fetch(`${config.baseUrl}/download/${sessionId}/${file.id}`, {
        headers: buildHeaders(config.apiKey, false),
      })
      if (!res.ok) {
        throw new Error(await res.text())
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.name
      link.click()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to download file', error)
    }
  }

  return (
    <div className="app-shell">
      <header>
        <h1>MCP Code Interpreter Dev UI</h1>
        <p>Quickly smoke-test the REST endpoints without curling by hand.</p>
      </header>

      <section className="panel">
        <h2>API Settings</h2>
        <div className="grid">
          <label>
            Base URL
            <input
              type="text"
              value={config.baseUrl}
              onChange={(e) => setConfig((c) => ({ ...c, baseUrl: e.target.value }))}
            />
          </label>
          <label>
            API Key (optional)
            <input
              type="password"
              value={config.apiKey}
              onChange={(e) => setConfig((c) => ({ ...c, apiKey: e.target.value }))}
            />
          </label>
          <label>
            Entity ID
            <input
              type="text"
              value={config.entityId}
              onChange={(e) => setConfig((c) => ({ ...c, entityId: e.target.value }))}
            />
          </label>
        </div>
        <div className="panel-actions">
          <button onClick={fetchHealth}>Refresh /health</button>
          <span className={`status ${healthStatus}`}>Status: {healthStatus}</span>
        </div>
        {availableRuntimes.length > 0 && (
          <table className="capabilities">
            <thead>
              <tr>
                <th>Runtime</th>
                <th>Available</th>
                <th>Missing binaries</th>
              </tr>
            </thead>
            <tbody>
              {availableRuntimes.map((runtime) => (
                <tr key={runtime.name}>
                  <td>{runtime.name}</td>
                  <td className={runtime.available ? 'ok' : 'warn'}>
                    {runtime.available ? 'yes' : 'no'}
                  </td>
                  <td>{runtime.missing.length ? runtime.missing.join(', ') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>1. Upload files (optional)</h2>
        <input type="file" multiple onChange={(e) => setSelectedFiles(e.target.files)} />
        <div className="panel-actions">
          <button onClick={handleUpload}>Upload</button>
          <span>{uploadStatus}</span>
        </div>
      </section>

      <section className="panel">
        <h2>2. Execute code</h2>
        <div className="grid">
          <label>
            Language
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((lang) => (
                <option key={lang.value} value={lang.value}>
                  {lang.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Args (optional)
            <input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="--flag value" />
          </label>
        </div>
        <label className="code-label">
          Code
          <textarea rows={10} value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <div className="panel-actions">
          <button onClick={handleExec}>Run /exec</button>
          <button disabled={language !== 'py' || streaming} onClick={handleStream}>
            {streaming ? 'Streaming…' : 'Run /exec/stream (Python)'}
          </button>
          <span className={`status ${execStatus === 'Success' ? 'success' : ''}`}>{execStatus}</span>
        </div>
        {execResult && (
          <pre className="output">
            {JSON.stringify(
              {
                session_id: execResult.session_id,
                stdout: execResult.run.stdout,
                stderr: execResult.run.stderr,
                code: execResult.run.code,
                status: execResult.run.status,
              },
              null,
              2,
            )}
          </pre>
        )}
        {streamLog && (
          <div>
            <h3>Stream output</h3>
            <pre className="output">{streamLog}</pre>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>3. Session files</h2>
        <div className="panel-actions">
          <button onClick={() => refreshFiles()}>Refresh files</button>
          {sessionId && <span>Current session: {sessionId}</span>}
        </div>
        {sessionFiles.length === 0 ? (
          <p>No files detected yet. Upload files or run code that writes to disk.</p>
        ) : (
          <table className="files">
            <thead>
              <tr>
                <th>Name</th>
                <th>Size</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessionFiles.map((file) => (
                <tr key={file.id}>
                  <td>{file.name}</td>
                  <td>{typeof file.size === 'number' ? `${file.size} bytes` : '—'}</td>
                  <td>
                    <button onClick={() => downloadFile(file)}>Download</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

export default App
