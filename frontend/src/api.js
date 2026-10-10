export async function api(path, method = 'GET', body) {
  const headers = { 'x-energy-action': '1' };
  if (body && !(body instanceof File)) headers['content-type'] = 'application/json';
  const response = await fetch('/api' + path, {
    method, headers, credentials: 'same-origin',
    body: body instanceof File ? body : body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.detail || 'The request failed. Please try again.');
    error.status = response.status;
    throw error;
  }
  return data;
}
