export interface RuntimeCapabilities {
  [runtime: string]: {
    available: boolean
    missing: string[]
    binaries: string[]
  }
}

export interface HealthResponse {
  status: string
  runtime_capabilities?: RuntimeCapabilities
  [key: string]: unknown
}

export interface UploadResponse {
  message: string
  session_id: string
  files: SessionFile[]
}

export interface SessionFile {
  id: string
  name: string
  session_id: string
  entity_id?: string | null
  path?: string
  contentType?: string | null
  size?: number
}

export interface ExecResponse {
  session_id: string
  language: string
  run: {
    stdout: string
    stderr: string
    code: number | null
    status?: string | null
    message?: string | null
  }
  files: Array<{ id: string; name: string; path: string }>
}
