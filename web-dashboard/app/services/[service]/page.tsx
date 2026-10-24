import {ServiceWorkspace} from '../../../components/resources/ServiceWorkspace';
export default async function Page({params}: {params: Promise<{service: string}>}) {
  const {service} = await params;
  return <ServiceWorkspace service={service}/>;
}
