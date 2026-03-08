import Link from "next/link";
import { Shield, Activity } from "lucide-react";

export function SiteHeader() {
  return (
    <header className="border-b border-border/50 bg-background/80 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-semibold text-lg">
          <Shield className="h-5 w-5 text-primary" />
          <span>Crypto Investigator</span>
        </Link>
        <nav className="flex items-center gap-4">
          <Link
            href="/feed"
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <Activity className="h-4 w-4" />
            <span>Feed</span>
          </Link>
        </nav>
      </div>
    </header>
  );
}
