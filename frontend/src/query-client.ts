// One QueryClient for the whole app; the provider in app/_layout.tsx uses
// this instance. Import it for cache calls outside components, for example
// queryClient.invalidateQueries or setQueryData in websocket or push
// handlers; inside components useQueryClient() returns this same instance.
import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/src/api";

// api() already retries network problems and 502/503/504 for up to ~60 s, so React Query must not repeat that
// (its default of 3 more retries would keep a screen loading for minutes before it shows an error). A definite answer
// (4xx) is never retried; other errors get one more try.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failures, error) => {
        if (error instanceof ApiError && (error.status === 0 || error.status < 500 || [502, 503, 504].includes(error.status))) return false;
        return failures < 1;
      },
    },
  },
});
