import React from 'react';

export const Spinner: React.FC = () => (
  <div className="flex justify-center items-center p-4">
    <div className="h-10 w-10 animate-pulse">
      <img
        src="/favicon.svg"
        alt="Loading"
        className="h-10 w-10 drop-shadow-sm animate-bounce"
        aria-hidden="true"
      />
      <span className="sr-only">Loading</span>
    </div>
  </div>
);
