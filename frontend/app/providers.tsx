"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { ClerkProvider, SignIn, useAuth } from "@clerk/nextjs";

const TokenContext=createContext<string|null>(null);
export function useAuthToken(){return useContext(TokenContext)}
export function Providers({children}:{children:React.ReactNode}){
 const publishableKey=process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
 if(!publishableKey)return <>{children}</>;
 return <ClerkProvider publishableKey={publishableKey}><ClerkGate>{children}</ClerkGate></ClerkProvider>;
}
function ClerkGate({children}:{children:React.ReactNode}){
 const {isLoaded,isSignedIn,getToken}=useAuth();const [token,setToken]=useState<string|null>(null);
 useEffect(()=>{if(isSignedIn)getToken().then(value=>setToken(value));else setToken(null)},[isSignedIn,getToken]);
 if(!isLoaded)return <main className="loading-screen"><div className="spinner"/><p>Loading your secure sign-in…</p></main>;
 if(!isSignedIn)return <main className="sign-in-screen"><div className="brand sign-in-brand"><span className="brand-mark">↗</span><span>cably<span className="brand-dot">.</span></span></div><SignIn routing="hash"/></main>;
 if(!token)return <main className="loading-screen"><div className="spinner"/><p>Verifying your session…</p></main>;
 return <TokenContext.Provider value={token}>{children}</TokenContext.Provider>;
}
