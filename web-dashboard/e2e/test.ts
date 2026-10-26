import {test as base,expect} from '@playwright/test';

/** Uncaught application errors fail a journey even if its visible assertions pass. */
export const test=base.extend({
  page:async({page},use)=>{
    const errors:string[]=[];
    page.on('pageerror',error=>errors.push(error.message));
    try{await use(page);}finally{expect(errors,'Unexpected browser runtime errors').toEqual([]);}
  },
});
export {expect};
export type {Page} from '@playwright/test';
