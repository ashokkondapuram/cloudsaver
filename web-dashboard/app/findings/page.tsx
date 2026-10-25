import {redirect} from 'next/navigation';
import {categories, type Category, type Intent, type Pricing} from '../../lib/resource-insights';

export default async function Page({searchParams}: {searchParams: Promise<{provider?: string; category?: string; intent?: string; pricing?: string; resource?: string}>}) {
  const params = await searchParams;
  const valid = (value: unknown, allowed: readonly string[]) => (typeof value === 'string' && allowed.includes(value) ? value : '');
  const next = new URLSearchParams();
  const provider = valid(params.provider, ['azure', 'aws', 'gcp', 'kubernetes']);
  const category = valid(params.category, categories.map(([id]) => id)) as Category | '';
  const intent = valid(params.intent, ['protected', 'review']) as Intent;
  const pricing = valid(params.pricing, ['known', 'unknown']) as Pricing;
  if (provider) next.set('provider', provider);
  if (category) next.set('category', category);
  if (intent) next.set('intent', intent);
  if (pricing) next.set('pricing', pricing);
  if (params.resource) next.set('resource', params.resource);
  const query = next.toString();
  redirect(query ? `/resources?${query}` : '/resources');
}
