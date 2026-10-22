import {ConsolePage} from '../../components/ConsolePage';
export default async function Page({searchParams}:{searchParams:Promise<{provider?:string}>}){
  const {provider}=await searchParams;
  return <ConsolePage view="findings" provider={typeof provider==='string'&&['azure','aws','gcp','kubernetes'].includes(provider)?provider:''}/>;
}
