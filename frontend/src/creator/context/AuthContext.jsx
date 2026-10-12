import axios from "axios";
import { useAuth as usePlatformAuth } from "../../context/AuthContext";

// Frasberg Creator shares the platform login (httpOnly cookie session).
axios.defaults.withCredentials = true;

export function AuthProvider({ children }) {
  return children;
}

export function useAuth() {
  const { user, login, register, logout } = usePlatformAuth();
  return { user: user || null, loading: user === undefined, token: null, authHeader: {}, login, register, logout };
}
