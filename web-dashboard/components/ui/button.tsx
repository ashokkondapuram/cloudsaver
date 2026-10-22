import * as React from 'react';
import {clsx} from 'clsx';
import {twMerge} from 'tailwind-merge';
// Local, shadcn-style owned primitive: native button semantics and token classes.
export function Button({className,...props}:React.ButtonHTMLAttributes<HTMLButtonElement>){return <button className={twMerge(clsx('button',className))} {...props}/>;}
