import {Suspense} from 'react';
import {ResourceInsightPage} from '../../../components/resources/ResourceInsightPage';

export default function Page() {
  return (
    <Suspense>
      <ResourceInsightPage/>
    </Suspense>
  );
}
