import { jwtDecode } from "jwt-decode";

const TOKEN_KEY = "advisor_token";
const USER_KEY = "advisor_user";

export interface User {
    id: string;
    email: string;
    name?: string;
    role: string;
    scopes: string[];
}


export const getToken = () => localStorage.getItem(TOKEN_KEY);

export const setToken = (token: string) => {
    localStorage.setItem(TOKEN_KEY, token);
};

export const getUser = (): User | null => {
    const user = localStorage.getItem(USER_KEY);
    return user ? JSON.parse(user) : null;
};

export const setUser = (user: User) => {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
};

export const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    window.location.reload();
};

export const isAuthenticated = () => {
    const token = getToken();
    if (!token) return false;
    try {
        const decoded: any = jwtDecode(token);
        return decoded.exp * 1000 > Date.now();
    } catch {
        return false;
    }
};
