import { FarmerAccess } from "../components/FarmerAccess";
import { Icon } from "../components/Icon";
import { PageHead } from "../components/Shell";
import { useApp } from "../state/store";
import type { ViewName } from "../lib/types";

/** Operator tools for the farmer app, on their own tab so the Plan tab stays about the plan and its pools. */
export function AccessView({ go }: { go: (v: ViewName) => void }) {
  const { state } = useApp();
  return (
    <>
      <PageHead title="Farmer access" lede="PINs, publishing the plan to farmers, printed cards and phone numbers." />
      <div className="stack">
        {!state.plan && (
          <div className="note" role="status"><Icon name="alert" small={false} /><span>No plan computed yet. You can still issue PINs; to publish, compute a plan on the Plan tab first.
            {" "}<button className="btn btn-secondary" type="button" onClick={() => go("dash")}>Go to Plan</button></span></div>
        )}
        <FarmerAccess />
      </div>
    </>
  );
}
