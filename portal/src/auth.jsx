import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getToken, portal, setToken } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return null;
    }
    try {
      const { user: me } = await portal.get("/me");
      setUser(me);
      return me;
    } catch (e) {
      if (e.status === 401) setToken("");
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (token) => {
      // No global loading state here: it would unmount the page that is about to navigate
      setToken(token);
      return refresh();
    },
    [refresh]
  );

  const signOut = useCallback(() => {
    setToken("");
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, loading, refresh, signIn, signOut, setUser }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

// "staff" (Zeptrax admins), "university_admin", "student", or "user" (main-site account without a university)
export const roleOf = (user) => user?.portal_role || "user";
