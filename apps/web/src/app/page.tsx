import { InvestigationForm } from "@/components/search/investigation-form";
import { RecentInvestigations } from "@/components/search/recent-investigations";
import { Shield, Activity, Zap } from "lucide-react";
import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col items-center min-h-[calc(100vh-3.5rem)]">
      {/* Hero */}
      <section className="w-full max-w-4xl mx-auto px-4 pt-20 pb-12 text-center space-y-6">
        <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-4 py-1.5 text-sm text-muted-foreground">
          <Zap className="h-3.5 w-3.5 text-yellow-400" />
          Autonomous Agent &mdash; Powered by Claude
        </div>
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight leading-tight">
          Investigate any Solana token
          <br />
          <span className="text-muted-foreground">in seconds.</span>
        </h1>
        <p className="max-w-xl mx-auto text-lg text-muted-foreground leading-relaxed">
          Paste a token address. Our agent traces deployer wallets, analyzes
          on-chain signals, checks infrastructure, and scores credibility
          from 0&ndash;100.
        </p>
      </section>

      {/* Search */}
      <section className="w-full max-w-xl mx-auto px-4 pb-8">
        <InvestigationForm />
      </section>

      {/* Recent */}
      <section className="w-full max-w-xl mx-auto px-4 pb-12">
        <RecentInvestigations />
      </section>

      {/* Feature cards */}
      <section className="w-full max-w-4xl mx-auto px-4 pb-20">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <FeatureCard
            icon={<Shield className="h-5 w-5 text-emerald-400" />}
            title="On-Chain Analysis"
            description="Deployer identification, funding chain tracing, holder concentration, and LP liquidity checks."
          />
          <FeatureCard
            icon={<Activity className="h-5 w-5 text-blue-400" />}
            title="Multi-Source Signals"
            description="12 signals from Helius, DexScreener, GitHub, infrastructure probing, and Bags launchpad."
          />
          <FeatureCard
            icon={<Zap className="h-5 w-5 text-yellow-400" />}
            title="AI Reasoning"
            description="Claude synthesizes all evidence into a scored verdict with auditability and transparency."
          />
        </div>
      </section>

      {/* Footer link */}
      <footer className="w-full border-t border-border/40 py-6 text-center text-sm text-muted-foreground">
        <Link href="/feed" className="hover:text-foreground transition-colors">
          View Live Investigation Feed &rarr;
        </Link>
      </footer>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-xl border border-border/50 bg-card p-5 space-y-3">
      <div className="flex items-center gap-2">
        {icon}
        <h3 className="font-medium">{title}</h3>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
    </div>
  );
}
