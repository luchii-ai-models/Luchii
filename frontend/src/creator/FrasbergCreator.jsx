import { useSearchParams } from "react-router-dom";
import CreatorShell, { CREATOR_TABS } from "./CreatorShell";
import Generator from "./pages/Generator";
import Models from "./pages/Models";
import ToolsTab from "./tabs/ToolsTab";

const VIEWS = { create: Generator, tools: ToolsTab, models: Models };
const ALIASES = { features: "tools" };

export default function FrasbergCreator() {
  const [params] = useSearchParams();
  const raw = ALIASES[params.get("tab")] || params.get("tab");
  const tab = CREATOR_TABS.some((t) => t.id === raw) ? raw : "create";
  const View = VIEWS[tab];
  return (
    <CreatorShell active={tab}>
      <div data-testid={`creator-view-${tab}`}><View /></div>
    </CreatorShell>
  );
}
