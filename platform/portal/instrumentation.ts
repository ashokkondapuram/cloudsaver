export async function register() {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  const {assertSafeStartup} = await import('./lib/server/startup');
  assertSafeStartup();
}
