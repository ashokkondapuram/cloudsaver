import {Suspense} from 'react';
import {GovernanceWorkspace} from '../../components/governance/GovernanceWorkspace';
export default function Page() {
  return (
    <Suspense fallback={null}>
      <GovernanceWorkspace />
    </Suspense>
  );
}
