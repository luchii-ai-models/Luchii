import React, { createContext, useContext, useEffect, useState } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem("luchii_token"));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const init = async () => {
      if (!token) {
        setLoading(false);
        return;
      }
      try {
        const res = await axios.get(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        setUser(res.data);
      } catch (e) {
        localStorage.removeItem("luchii_token");
        setToken(null);
      } finally {
        setLoading(false);
      }
    };
    init();
  }, [token]);

  const persist = (data) => {
    localStorage.setItem("luchii_token", data.token);
    setToken(data.token);
    setUser(data.user);
  };

  const register = async (name, email, password) => {
    const res = await axios.post(`${API}/auth/register`, { name, email, password });
    persist(res.data);
  };

  const login = async (email, password) => {
    const res = await axios.post(`${API}/auth/login`, { email, password });
    persist(res.data);
  };

  const logout = () => {
    localStorage.removeItem("luchii_token");
    setToken(null);
    setUser(null);
  };

  const authHeader = token ? { Authorization: `Bearer ${token}` } : {};

  // Auto-publish: send each new image straight to the public homepage gallery.
  const setAutoPublish = async (on) => {
    const res = await axios.put(`${API}/me/settings`, { auto_publish: on }, { headers: authHeader });
    setUser((u) => (u ? { ...u, auto_publish: res.data.auto_publish } : u));
    return res.data.auto_publish;
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, register, login, logout, authHeader, setAutoPublish }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
