import { Suspense } from "react";
import { KioskFlow } from "./KioskFlow";

export default function KioskPage() {
  return (
    <Suspense>
      <KioskFlow />
    </Suspense>
  );
}
