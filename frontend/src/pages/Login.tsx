import { GoogleLogin } from "@react-oauth/google";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { setToken, setUser, getToken } from "@/lib/auth";
import { toast } from "sonner";

const Login = () => {
    const navigate = useNavigate();

    const handleSuccess = async (response: any) => {
        try {
            console.log("Google Login success, exchanging token...");
            // Exchange Google ID Token for our own JWT
            const res = await fetch("http://localhost:8000/auth/login/google", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id_token: response.credential }),
            });

            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.detail || "Backend authentication failed");
            }

            const data = await res.json();
            setToken(data.access_token);
            setUser({ id: data.user_id, email: data.email, name: data.name, role: data.role ?? "user", scopes: data.scopes ?? [] });

            toast.success("Welcome back!");
            navigate("/");
        } catch (err: any) {
            console.error("Auth Error:", err);
            toast.error(err.message || "Login failed. Please try again.");
        }
    };


    return (
        <div className="min-h-screen flex items-center justify-center bg-[#010101] overflow-hidden relative">
            {/* Background Glows */}
            <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-500/10 blur-[120px] rounded-full" />
            <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-purple-500/10 blur-[120px] rounded-full" />

            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.8, ease: "easeOut" }}
                className="z-10 w-full max-w-md p-8 bg-[#0a0a0a]/80 backdrop-blur-xl border border-white/10 rounded-3xl shadow-2xl text-center"
            >
                <div className="mb-8">
                    <div className="flex justify-center mb-4">
                        <div className="p-4 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl shadow-lg ring-1 ring-white/20">
                            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                                <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
                            </svg>
                        </div>
                    </div>
                    <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-white/60 mb-2">
                        AI Financial Advisor
                    </h1>
                    <p className="text-white/40">Secure multi-tenant portal</p>
                </div>

                <div className="flex justify-center py-4">
                    <GoogleLogin
                        onSuccess={handleSuccess}
                        onError={() => toast.error("Google login failed")}
                        useOneTap
                        shape="pill"
                        theme="filled_black"
                    />
                </div>

                <p className="mt-8 text-xs text-white/20">
                    Professional Identity Management via Google OAuth 2.0
                </p>
            </motion.div>
        </div>
    );
};

export default Login;
