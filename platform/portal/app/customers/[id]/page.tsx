import {CustomerDetail} from '../../../components/customers/CustomerDetail';

export const metadata = {title: 'Customer | CloudSaver platform portal'};

export default async function CustomerPage({params}: {params: Promise<{id: string}>}) {
  const {id} = await params;
  return <CustomerDetail id={id}/>;
}
