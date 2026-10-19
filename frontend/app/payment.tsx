"use client";
import { useState } from "react";
import { CardElement, Elements, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { ArrowRight, Check, CreditCard, LoaderCircle, X } from "lucide-react";
const stripeKey=process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;const stripePromise=stripeKey?loadStripe(stripeKey):null;
function CardForm({clientSecret,onComplete}:{clientSecret:string;onComplete:(paymentIntentId:string)=>Promise<void>}){
 const stripe=useStripe(),elements=useElements();const [busy,setBusy]=useState(false),[error,setError]=useState("");
 async function submit(e:React.FormEvent){e.preventDefault();if(!stripe||!elements)return;setBusy(true);setError("");const card=elements.getElement(CardElement);if(!card){setBusy(false);return}try{const result=await stripe.confirmCardPayment(clientSecret,{payment_method:{card}});if(result.error)setError(result.error.message||"Payment could not be completed");else if(result.paymentIntent?.status==="succeeded")await onComplete(result.paymentIntent.id)}catch(e:any){setError(e.message||"Payment confirmation failed")}finally{setBusy(false)}}
 return <form onSubmit={submit}><div className="card-input"><CardElement options={{hidePostalCode:true,style:{base:{fontSize:"14px",fontFamily:"DM Sans, sans-serif",color:"#26332d","::placeholder":{color:"#9ba59f"}}}}}/></div>{error&&<p className="payment-error">{error}</p>}<button className="primary-button full-button" disabled={!stripe||busy}>{busy?<><LoaderCircle className="spin-icon" size={16}/> Processing…</>:<>Pay securely <ArrowRight size={16}/></>}</button><p className="payment-secure"><CreditCard size={13}/> Secure payment powered by Stripe</p></form>
}
export default function PaymentModal({clientSecret,amount,onComplete,onClose}:{clientSecret:string;amount:string;onComplete:(paymentIntentId:string)=>Promise<void>;onClose:()=>void}){
 return <div className="modal-backdrop" onClick={onClose}><section className="review-modal payment-modal" onClick={e=>e.stopPropagation()}><button className="modal-close" onClick={onClose}><X size={18}/></button><span className="review-spark payment-spark"><CreditCard size={21}/></span><div className="eyebrow">SECURE CHECKOUT</div><h2>Complete your payment</h2><p>Payment total <b>{amount}</b></p><Elements stripe={stripePromise} options={{clientSecret,appearance:{theme:"stripe",variables:{colorPrimary:"#087e5b",borderRadius:"7px"}}}}><CardForm clientSecret={clientSecret} onComplete={onComplete}/></Elements></section></div>
}
