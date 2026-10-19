"use client";
import { useState } from "react";
import { ArrowRight, Headphones, MessageSquare, Send, X } from "lucide-react";

const answers: Record<string, string> = {
  "Where is my driver?": "Open Ride history to see your current ride and its status. Driver location updates appear while the trip is active.",
  "How do card payments work?": "Card checkout uses Stripe. This local demo needs Stripe test keys before it can open a real Stripe card form. Wallet payments are available from Ride history.",
  "I need help with a ride": "Open Ride history and select the ride. For help from the Cably team, email hello@cably.app with the ride details.",
};

export default function SupportChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<{from:"support"|"you"; text:string}[]>([
    { from: "support", text: "Hi! I’m Cably’s help assistant. What can I help you with? For a person, email hello@cably.app." },
  ]);
  const [draft, setDraft] = useState("");
  function send(text = draft) {
    const message = text.trim();
    if (!message) return;
    setMessages(current => [...current, { from: "you", text: message }, { from: "support", text: answers[message] || "I can help with common ride and payment questions. For a person to follow up, email hello@cably.app and include your ride details." }]);
    setDraft("");
  }
  return <>
    <button className="support-chat-launch" onClick={() => setOpen(true)}><MessageSquare size={16}/> Chat with us</button>
    {open && <div className="support-chat-panel" role="dialog" aria-label="Cably help chat">
      <header><span><Headphones size={17}/> Cably help <small>Help assistant</small></span><button aria-label="Close chat" onClick={() => setOpen(false)}><X size={18}/></button></header>
      <div className="support-chat-messages" aria-live="polite">{messages.map((message, index) => <p key={index} className={`chat-message ${message.from}`}>{message.text}</p>)}
        {messages.length === 1 && <div className="chat-suggestions">{Object.keys(answers).map(question => <button key={question} onClick={() => send(question)}>{question}<ArrowRight size={13}/></button>)}</div>}
      </div>
      <form onSubmit={event => { event.preventDefault(); send(); }}><input value={draft} onChange={event => setDraft(event.target.value)} placeholder="Type a message…" aria-label="Type a message"/><button aria-label="Send message" disabled={!draft.trim()}><Send size={16}/></button></form>
      <div className="support-chat-note">Automated help · Email <a href="mailto:hello@cably.app">hello@cably.app</a> for a person</div>
    </div>}
  </>;
}
