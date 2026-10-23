import {ConsolePage} from '../../components/ConsolePage';
import {categories,type Category,type Intent,type Pricing} from '../../lib/resource-insights';
export default async function Page({searchParams}:{searchParams:Promise<{provider?:string;category?:string;intent?:string;pricing?:string}>}){
  const params=await searchParams;
  const valid=(value:unknown,allowed:readonly string[])=>typeof value==='string'&&allowed.includes(value)?value:'';
  return <ConsolePage view="findings" provider={valid(params.provider,['azure','aws','gcp','kubernetes'])}
    category={valid(params.category,categories.map(([id])=>id)) as Category|''} intent={valid(params.intent,['protected','review']) as Intent} pricing={valid(params.pricing,['known','unknown']) as Pricing}/>;
}
