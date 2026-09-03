import { AuthGate } from "@/components/auth-gate";
import { ThreePanelInterface } from "@/components/three-panel-interface";

export default function Home() {
  return (
    <main className="h-screen bg-background">
      <AuthGate>
        <ThreePanelInterface />
      </AuthGate>
    </main>
  );
}
