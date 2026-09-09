import { createContext, useContext, useState } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('verireview_user')
    return saved ? JSON.parse(saved) : null
  })

  const register = (name, email) => {
    const cleanEmail = (email || "").trim().toLowerCase();
    const newUser = { name, email: cleanEmail }
    localStorage.setItem('verireview_user', JSON.stringify(newUser))
    setUser(newUser)
  }

  const login = (email) => {
    const cleanEmail = (email || "").trim().toLowerCase();
    const existing = { name: cleanEmail.split('@')[0], email: cleanEmail }
    localStorage.setItem('verireview_user', JSON.stringify(existing))
    setUser(existing)
  }

  const logout = () => {
    localStorage.removeItem('verireview_user')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}