import {ServiceWorkspace} from '../../../components/V150Views';
export default async function Page({params}:{params:Promise<{service:string}>}){const {service}=await params;return <ServiceWorkspace service={service}/>;}
