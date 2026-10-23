import {Suspense} from 'react';
import {ConsolePage} from '../../components/ConsolePage';
export default function Page(){
  return <Suspense><ConsolePage view="resources"/></Suspense>;
}
