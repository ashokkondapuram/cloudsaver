import {WorkspaceDetail} from '../../../components/workspaces/WorkspaceDetail';

export const metadata = {title: 'Workspace | CloudSaver platform portal'};

export default async function WorkspacePage({params}: {params: Promise<{tenantId: string}>}) {
  const {tenantId} = await params;
  return <WorkspaceDetail tenantId={tenantId}/>;
}
