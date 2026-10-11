import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// The app keeps the sign-in token in localStorage; start every test signed out.
afterEach(() => {
  cleanup()
  localStorage.clear()
})
