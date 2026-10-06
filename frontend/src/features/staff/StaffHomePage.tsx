import { useMe } from "@/lib/auth";
import { KitchenPage } from "./KitchenPage";
import { PrintQueuePage } from "./PrintQueuePage";

/** Staff home: the kitchen board for canteen staff, the print queue for print staff. */
export function StaffHomePage() {
  const me = useMe().data;
  return me?.role === "print" ? <PrintQueuePage /> : <KitchenPage />;
}
