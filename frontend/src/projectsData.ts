import { useEffect, useState } from 'react'
import { j } from './ui'

export type Project = {
  id: string
  name: string
  path: string
  default?: boolean
  ready?: boolean
  mode?: 'dbt' | 'sql' | 'unsupported'
  adapter?: string | null
  dialect?: string
  dbt_dir_rel?: string
  profile?: string
  profiles_source?: string
  dev_target?: string
  prod_target?: string | null
  dbt_version?: string
  errors?: string[]
  warnings?: string[]
}
type TaskLike = { id: string; project_id?: string; project_name?: string }

const LS_KEY = 'factory.project'
/** Selected project id (as remembered by the picker); '' means the server default. */
export const selectedProjectId = () => localStorage.getItem(LS_KEY) || ''

/** Registered projects + the current selection (persisted per browser). */
export function useProjects(defaultId?: string) {
  const [projects, setProjects] = useState<Project[]>([])
  const [cur, setCurState] = useState<string>(localStorage.getItem(LS_KEY) || '')
  const refresh = (hard = false) =>
    j(`/api/projects${hard ? '?refresh=true' : ''}`)
      .then(setProjects)
      .catch(() => setProjects([]))
  useEffect(() => {
    refresh()
  }, [])
  const setCur = (id: string) => {
    localStorage.setItem(LS_KEY, id)
    setCurState(id)
  }
  const current = projects.find((p) => p.id === cur) || projects.find((p) => p.id === defaultId) || projects[0]
  return { projects, current, setCur, refresh }
}

/** Sessions grouped by the project they ran against (sidebar). */
export function groupByProject<T extends TaskLike>(tasks: T[], projects: Project[], fallbackId?: string) {
  const name = (id: string, t?: T) => projects.find((p) => p.id === id)?.name || t?.project_name || 'project'
  const groups = new Map<string, { id: string; name: string; tasks: T[] }>()
  for (const p of projects) groups.set(p.id, { id: p.id, name: p.name, tasks: [] })
  for (const t of tasks) {
    const id = t.project_id || fallbackId || 'default'
    if (!groups.has(id)) groups.set(id, { id, name: name(id, t), tasks: [] })
    groups.get(id)!.tasks.push(t)
  }
  return [...groups.values()].filter((g) => g.tasks.length || projects.some((p) => p.id === g.id))
}
