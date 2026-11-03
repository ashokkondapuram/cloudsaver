import {Suspense} from 'react';
import {WorkloadsView} from '../../components/workloads/WorkloadsView';

export default function Page() {
  return (
    <Suspense fallback={null}>
      <WorkloadsView />
    </Suspense>
  );
}
