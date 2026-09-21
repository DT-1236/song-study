import { createContext, useContext, type ReactNode } from 'react'
import { LOGIN_URL, fetchCurrentUser, type CurrentUser } from './api'
import { useApiResource } from './useApiResource'

const UserContext = createContext<CurrentUser | null>(null)

export function useCurrentUser(): CurrentUser {
  const user = useContext(UserContext)
  if (user === null)
    throw new Error('useCurrentUser must be used inside AuthGate')
  return user
}

// Renders its children only for a logged-in user, and otherwise a link to
// log in with Google.
export function AuthGate({ children }: { children: ReactNode }) {
  const {
    data: user,
    loading,
    error,
  } = useApiResource(fetchCurrentUser, [], 'Could not reach the server.')

  if (loading) return null
  if (error) return <p className="login-page">{error}</p>
  if (user === null) {
    return (
      <div className="login-page">
        <h1>Song Study</h1>
        <a className="login-button" href={LOGIN_URL}>
          Log in with Google
        </a>
      </div>
    )
  }
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>
}
