import React from 'react';
import { GitBranch, ShieldAlert, KeyRound, Globe, ArrowRight, CheckCircle2 } from 'lucide-react';

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center p-6">
      <div className="max-w-xl w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Repository Access Required</h1>
            <p className="text-xs text-slate-400 font-mono">adamkerrnz/kerrchowfit</p>
          </div>
        </div>

        <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4 mb-6">
          <p className="text-sm text-slate-300 leading-relaxed">
            The repository <span className="font-semibold text-white">adamkerrnz/kerrchowfit</span> is currently private or inaccessible without authentication credentials.
          </p>
        </div>

        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">
          How to proceed:
        </h2>

        <div className="space-y-4 mb-8">
          <div className="flex gap-4 p-4 rounded-xl bg-slate-800/50 border border-slate-750">
            <div className="mt-0.5 text-indigo-400">
              <Globe className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-white mb-1">Option 1: Temporarily make repository Public</h3>
              <p className="text-xs text-slate-400 leading-relaxed mb-2">
                On GitHub, go to <span className="text-slate-300 font-mono">Settings &rarr; Danger Zone &rarr; Change visibility &rarr; Make public</span>, then reply here so the app can pull and initialize your project immediately.
              </p>
            </div>
          </div>

          <div className="flex gap-4 p-4 rounded-xl bg-slate-800/50 border border-slate-750">
            <div className="mt-0.5 text-emerald-400">
              <KeyRound className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-white mb-1">Option 2: Provide a GitHub Personal Access Token</h3>
              <p className="text-xs text-slate-400 leading-relaxed mb-2">
                Create a fine-grained or classic token with <span className="text-slate-300 font-mono">repo</span> read scope at <span className="text-slate-300 font-mono">github.com/settings/tokens</span>, then reply in chat with:
              </p>
              <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800 font-mono text-xs text-slate-300 select-all">
                Pull from https://&lt;YOUR_TOKEN&gt;@github.com/adamkerrnz/kerrchowfit.git
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between pt-4 border-t border-slate-800/80 text-xs text-slate-400">
          <span className="flex items-center gap-1.5">
            <GitBranch className="w-4 h-4 text-slate-500" />
            Vite + React dev environment ready
          </span>
          <span className="text-slate-500 font-mono">Port 3000</span>
        </div>
      </div>
    </div>
  );
}
