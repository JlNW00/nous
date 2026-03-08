import Link from "next/link";
import { Shield } from "lucide-react";

export function SiteHeader() {
  return (
    <header className="border-b border-border/50 bg-background/80 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-semibold text-lg">
          <Shield className="h-5 w-5 text-primary" />
          <span>Crypto Investigator</span>
        </Link>
      </div>
    </header>
  );
}
