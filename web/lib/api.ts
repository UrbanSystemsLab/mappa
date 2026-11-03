// Where the API is: this same site by default. The current frontend reads the
// same setting as window.MAPPA_API_ORIGIN.
export const API_ORIGIN = (process.env.NEXT_PUBLIC_MAPPA_API_ORIGIN || '').replace(/\/$/, '');
export const API = `${API_ORIGIN}/api/v1`;
