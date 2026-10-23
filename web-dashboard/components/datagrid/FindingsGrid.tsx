'use client';

import {useEffect, useMemo, useRef, useState, type CSSProperties, type InputHTMLAttributes} from 'react';
import {ColumnDef, ColumnOrderState, ColumnPinningState, RowSelectionState, SortingState, VisibilityState, flexRender, getCoreRowModel, getPaginationRowModel, getSortedRowModel, useReactTable, type Column} from '@tanstack/react-table';
import {useVirtualizer} from '@tanstack/react-virtual';
import {ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpDown, Blocks, Check, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Columns3, Download, FileCode2, Filter, Search, SlidersHorizontal, X} from 'lucide-react';
import {exportFindings, findingKey, money, observedTags, providerOf, providerNames, ruleLabel, scopeOf} from '../../lib/finops';
import type {Finding} from '../../lib/types';
import {useWorkspace} from '../WorkspaceProvider';
import {useScopedFindings} from '../Overview';
import {EmptyState, PriorityBadge, ProviderBadge} from '../ui/shared';

function Checkbox({indeterminate = false, ...props}: InputHTMLAttributes<HTMLInputElement> & {indeterminate?: boolean}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {if (ref.current) ref.current.indeterminate = indeterminate;}, [indeterminate]);
  return <input type="checkbox" ref={ref} {...props}/>;
}

const initialOrder = ['select','resource','signal','provider','scope','monthly','savings','priority','actions'];
function pinnedStyle(column: Column<Finding>): CSSProperties {
  const pinned = column.getIsPinned();
  return {width:column.getSize(), minWidth:column.getSize(), ...(pinned ? {
    position:'sticky', left:pinned === 'left' ? column.getStart('left') : undefined,
    right:pinned === 'right' ? column.getAfter('right') : undefined,
    zIndex:2, background:'var(--row-background, var(--surface))',
    boxShadow:column.getIsLastColumn('left') ? '1px 0 0 var(--border)' : column.getIsFirstColumn('right') ? '-1px 0 0 var(--border)' : undefined,
  } : {})};
}

export function FindingsGrid({initialProvider = ''}: {initialProvider?: string}) {
  const {scan,openFinding,scope,setScope,selection,setSelection,openReview,density,setDensity,notify} = useWorkspace();
  const findings = useScopedFindings();
  const [query,setQuery] = useState(''), [provider,setProvider] = useState(initialProvider), [severity,setSeverity] = useState(''), [type,setType] = useState(''), [tag,setTag] = useState('');
  const [sorting,setSorting] = useState<SortingState>([{id:'priority',desc:false}]);
  const [rowSelection,setRowSelection] = useState<RowSelectionState>({});
  const [visibility,setVisibility] = useState<VisibilityState>({savings:false});
  const [order,setOrder] = useState<ColumnOrderState>(initialOrder);
  const [pinning,setPinning] = useState<ColumnPinningState>({left:['select','resource'],right:['actions']});
  const [pagination,setPagination] = useState({pageIndex:0,pageSize:100});
  const scroller = useRef<HTMLDivElement>(null), search = useRef<HTMLInputElement>(null), columnMenu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {setProvider(initialProvider);}, [initialProvider]);
  useEffect(() => {setRowSelection({});setSelection([]);setPagination(previous => ({...previous,pageIndex:0}));}, [query,provider,severity,type,tag,scope,scan?.scan_id,setSelection]);
  const filtered = useMemo(() => findings.filter(f => {
    const tags = observedTags(f);
    const match = !tag.trim() || (tag.includes('=') ? tags[tag.slice(0,tag.indexOf('='))] === tag.slice(tag.indexOf('=')+1) : Object.keys(tags).some(key => key.toLowerCase().includes(tag.toLowerCase())));
    return (!provider || providerOf(f) === provider) && (!severity || f.severity === severity) && (!type || f.resource_type === type) && match &&
      `${f.resource_name} ${f.resource_group} ${scopeOf(f)} ${f.resource_id} ${ruleLabel(f.rule_id)}`.toLowerCase().includes(query.toLowerCase());
  }), [findings,query,provider,severity,type,tag]);

  const columns = useMemo<ColumnDef<Finding>[]>(() => [
    {id:'select',size:44,enableSorting:false,enableHiding:false,header:({table}) => <Checkbox aria-label="Select all findings on this page" checked={table.getIsAllPageRowsSelected()} indeterminate={table.getIsSomePageRowsSelected()} onChange={table.getToggleAllPageRowsSelectedHandler()}/>,cell:({row}) => <Checkbox aria-label={`Select ${row.original.resource_name}`} checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} onClick={e => e.stopPropagation()}/>},
    {id:'resource',accessorKey:'resource_name',header:'Resource',size:260,enableHiding:false,cell:({row}) => <button data-focus-return={findingKey(row.original)} className="resource-name" onClick={e => {e.stopPropagation();openFinding(row.original);}}><strong>{row.original.resource_name}</strong><small>{row.original.resource_type.split('/').slice(-1)[0]}</small></button>},
    {id:'signal',accessorFn:f => ruleLabel(f.rule_id),header:'Finding',size:225,cell:({row}) => <span className="signal-cell" title={ruleLabel(row.original.rule_id)}>{ruleLabel(row.original.rule_id)}</span>},
    {id:'provider',accessorFn:providerOf,header:'Provider',size:145,cell:({row}) => <ProviderBadge provider={providerOf(row.original)}/>},
    {id:'scope',accessorFn:scopeOf,header:'Account / scope',size:220,cell:({row}) => <span className="scope-cell"><span title={row.original.resource_group}>{row.original.resource_group || '—'}</span><small title={scopeOf(row.original)}>{scopeOf(row.original)}</small></span>},
    {id:'monthly',accessorFn:f => f.estimated_monthly_waste_usd ?? undefined,sortUndefined:'last',header:'Monthly estimate',size:160,cell:({row}) => <span className={row.original.estimated_monthly_waste_usd === null ? 'unpriced-cell' : 'money-cell'}>{money(row.original.estimated_monthly_waste_usd)}</span>},
    {id:'savings',accessorFn:f => f.cost_attribution?.realizable_savings_usd ?? undefined,sortUndefined:'last',header:'Net savings',size:150,cell:({row}) => <span className={row.original.cost_attribution?.realizable_savings_usd == null ? 'unpriced-cell' : 'money-cell'}>{money(row.original.cost_attribution?.realizable_savings_usd)}</span>},
    {id:'priority',accessorKey:'severity',header:'Priority',size:120,sortingFn:(a,b) => {const rank:Record<string,number>={CRITICAL:0,HIGH:1,MEDIUM:2,LOW:3,INFO:4};return (rank[a.original.severity] ?? 5) - (rank[b.original.severity] ?? 5);},cell:({row}) => <PriorityBadge severity={row.original.severity}/>},
    {id:'actions',size:46,enableSorting:false,enableHiding:false,header:() => <span className="sr-only">Open</span>,cell:({row}) => <button className="icon-button" data-focus-return={`action:${findingKey(row.original)}`} aria-label={`View details for ${row.original.resource_name}`} onClick={e => {e.stopPropagation();openFinding(row.original);}}><ChevronRight size={16}/></button>},
  ], [openFinding]);

  const table = useReactTable({data:filtered,columns,getRowId:findingKey,
    state:{sorting,rowSelection,columnVisibility:visibility,columnOrder:order,columnPinning:pinning,pagination},
    onSortingChange:setSorting,onRowSelectionChange:update => {const next=typeof update==='function'?update(rowSelection):update;setRowSelection(next);setSelection(filtered.filter(f=>!!next[findingKey(f)]));},onColumnVisibilityChange:setVisibility,onColumnOrderChange:setOrder,onColumnPinningChange:setPinning,onPaginationChange:setPagination,
    getCoreRowModel:getCoreRowModel(),getSortedRowModel:getSortedRowModel(),getPaginationRowModel:getPaginationRowModel(),autoResetPageIndex:false});
  const selected = useMemo(() => table.getSelectedRowModel().rows.map(row => row.original), [rowSelection,filtered]);
  useEffect(() => () => setSelection([]), [setSelection]);
  const rows = table.getRowModel().rows;
  const rowHeight = density === 'compact' ? 28 : density === 'medium' ? 36 : 48;
  const virtual = useVirtualizer({count:rows.length,getScrollElement:() => scroller.current,estimateSize:() => rowHeight,overscan:10});
  useEffect(() => {virtual.measure();}, [density]);
  useEffect(() => {scroller.current?.scrollTo({top:0});}, [pagination.pageIndex,query,provider,severity,type,tag]);
  const items = virtual.getVirtualItems();
  const options = table.getAllLeafColumns().filter(column => column.getCanHide());
  function move(id:string,direction:number) {setOrder(previous => {const next=[...previous],index=next.indexOf(id),target=index+direction;if(target>0&&target<next.length-1)[next[index],next[target]]=[next[target],next[index]];return next;});}
  function reset() {setQuery('');setProvider('');setSeverity('');setType('');setTag('');setScope([]);}
  function exportSelection(kind:'csv'|'json') {exportFindings(selected,kind,`cloudsaver-${scan?.scan_id}-selected`);notify(`${kind.toUpperCase()} download prepared for ${selected.length} findings.`);}
  const chips = [query && {label:`Search: ${query}`,clear:()=>setQuery('')},provider && {label:providerNames[provider] || provider,clear:()=>setProvider('')},severity && {label:`Priority: ${severity.toLowerCase()}`,clear:()=>setSeverity('')},type && {label:type.split('/').slice(-1)[0],clear:()=>setType('')},tag && {label:`Tag: ${tag}`,clear:()=>setTag('')},scope.length>0 && {label:`${scope.length} scope filters`,clear:()=>setScope([])}].filter(Boolean) as {label:string;clear:()=>void}[];
  return <section className={`panel findings-grid density-${density}`} data-inventory="true" aria-label="Findings inventory" onKeyDown={e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'a' && !(e.target as HTMLElement).closest('input[type="search"],input[type="text"]')) {e.preventDefault();table.toggleAllPageRowsSelected(true);}
    if(e.key === '/' && !(e.target as HTMLElement).closest('input,select')) {e.preventDefault();search.current?.focus();}
    if(e.key === 'Escape' && columnMenu.current) columnMenu.current.open=false;
  }}>
    <div className="grid-heading"><div><h2>Resource findings <span className="count-badge">{filtered.length.toLocaleString()}</span></h2><p>Review signals, pricing evidence, and resource context.</p></div><div className="grid-display-controls"><div className="segmented-control density-controls" aria-label="Row density">{(['compact','medium','relaxed'] as const).map(value => <button key={value} aria-label={`${value} density`} aria-pressed={density===value} title={`${value} · ${value==='compact'?28:value==='medium'?36:48}px rows`} onClick={() => setDensity(value)}><span className={`density-glyph ${value}`} aria-hidden="true"><i/><i/><i/></span></button>)}</div><details ref={columnMenu} className="column-menu"><summary className="button secondary"><Columns3 size={15}/>Columns<ChevronRight size={13}/></summary><div className="menu-surface"><span className="menu-label">CUSTOMIZE YOUR VIEW</span>{options.map(column => <div key={column.id} className="column-option"><label><input type="checkbox" checked={column.getIsVisible()} onChange={column.getToggleVisibilityHandler()}/>{typeof column.columnDef.header==='string'?column.columnDef.header:column.id}</label><div><button className="icon-button" title="Move column earlier" aria-label={`Move ${column.id} column earlier`} onClick={() => move(column.id,-1)}><ArrowLeft size={13}/></button><button className="icon-button" title="Move column later" aria-label={`Move ${column.id} column later`} onClick={() => move(column.id,1)}><ArrowRight size={13}/></button><button className={`pin-control ${column.getIsPinned()==='left'?'pinned':''}`} aria-label={`Pin ${column.id} column left`} aria-pressed={column.getIsPinned()==='left'} onClick={() => column.pin(column.getIsPinned()==='left'?false:'left')}>L</button><button className={`pin-control ${column.getIsPinned()==='right'?'pinned':''}`} aria-label={`Pin ${column.id} column right`} aria-pressed={column.getIsPinned()==='right'} onClick={() => column.pin(column.getIsPinned()==='right'?false:'right')}>R</button></div></div>)}<button className="text-button" onClick={() => {setVisibility({savings:false});setOrder(initialOrder);setPinning({left:['select','resource'],right:['actions']});}}>Reset columns</button></div></details></div></div>
    <div className="grid-filters"><label className="grid-search"><Search size={16}/><input ref={search} type="search" aria-label="Search findings" placeholder="Search resources, IDs, or findings…" value={query} onChange={e => setQuery(e.target.value)}/><kbd>/</kbd></label><label><span className="sr-only">Cloud provider</span><select aria-label="Cloud provider" value={provider} onChange={e => setProvider(e.target.value)}><option value="">All providers</option>{[...new Set((scan?.findings||[]).map(providerOf))].sort().map(p => <option key={p} value={p}>{providerNames[p]||p}</option>)}</select></label><label><span className="sr-only">Finding priority</span><select aria-label="Finding priority" value={severity} onChange={e => setSeverity(e.target.value)}><option value="">All priorities</option>{['CRITICAL','HIGH','MEDIUM','LOW','INFO'].map(s => <option key={s} value={s}>{s.charAt(0)+s.slice(1).toLowerCase()}</option>)}</select></label><label><span className="sr-only">Resource type</span><select aria-label="Resource type" value={type} onChange={e => setType(e.target.value)}><option value="">All resource types</option>{[...new Set((scan?.findings||[]).map(f=>f.resource_type))].sort().map(t => <option key={t} value={t}>{t.split('/').slice(-1)[0]}</option>)}</select></label><label className="tag-filter"><span className="sr-only">Tag filter</span><input type="text" aria-label="Tag filter" placeholder="Tag key=value" value={tag} onChange={e => setTag(e.target.value)}/></label></div>
    {!!chips.length && <div className="active-filters"><Filter size={13}/>{chips.map(chip => <button key={chip.label} onClick={chip.clear} aria-label={`Remove filter ${chip.label}`}>{chip.label}<X size={12}/></button>)}<button className="clear-filters" onClick={reset}>Clear all</button></div>}
    <div className="grid-scroll" ref={scroller} tabIndex={0} aria-label="Scrollable findings table">
      <table className="data-table" style={{width:table.getTotalSize()}} aria-rowcount={filtered.length + 1}>
        <thead>{table.getHeaderGroups().map(group => <tr key={group.id}>{group.headers.map(header => <th key={header.id} style={{...pinnedStyle(header.column),background:'var(--slate-50)',zIndex:header.column.getIsPinned()?4:3}} aria-sort={header.column.getIsSorted()==='asc'?'ascending':header.column.getIsSorted()==='desc'?'descending':undefined}>{header.column.getCanSort()?<button onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header,header.getContext())}{header.column.getIsSorted()==='asc'?<ArrowUp size={12}/>:header.column.getIsSorted()==='desc'?<ArrowDown size={12}/>:<ArrowUpDown size={12}/>}</button>:flexRender(header.column.columnDef.header,header.getContext())}</th>)}</tr>)}</thead>
        <tbody>{items.length>0&&<tr aria-hidden="true"><td colSpan={table.getVisibleLeafColumns().length} style={{height:items[0].start,padding:0,border:0}}/></tr>}{items.map(item => {const row=rows[item.index];return <tr key={row.id} className={row.getIsSelected()?'row-selected':''} style={{height:rowHeight}} aria-selected={row.getIsSelected()} aria-rowindex={pagination.pageIndex*pagination.pageSize+item.index+2} onClick={() => openFinding(row.original)}>{row.getVisibleCells().map(cell => <td key={cell.id} style={pinnedStyle(cell.column)}>{flexRender(cell.column.columnDef.cell,cell.getContext())}</td>)}</tr>;})}{items.length>0&&<tr aria-hidden="true"><td colSpan={table.getVisibleLeafColumns().length} style={{height:Math.max(0,virtual.getTotalSize()-items[items.length-1].end),padding:0,border:0}}/></tr>}{!filtered.length&&<tr><td colSpan={table.getVisibleLeafColumns().length}><EmptyState icon={Search} title={findings.length?'No matching findings':'No findings in this scope'}>{findings.length?'Try a broader search or remove a filter.':'Select another scope or scan snapshot to explore resource signals.'}{!!chips.length&&<button className="button secondary" onClick={reset}>Reset filters</button>}</EmptyState></td></tr>}</tbody>
      </table>
    </div>
    <div className="grid-footer"><span>{selected.length ? `${selected.length.toLocaleString()} selected · ` : ''}{filtered.length.toLocaleString()} matching findings</span><div className="pagination"><label>Rows<select aria-label="Rows per page" value={pagination.pageSize} onChange={e => {table.setPageSize(Number(e.target.value));table.setPageIndex(0);}}>{[50,100,250].map(n => <option key={n} value={n}>{n}</option>)}</select></label><span>{filtered.length ? pagination.pageIndex+1 : 0} of {table.getPageCount()}</span><button className="icon-button" aria-label="First page" disabled={!table.getCanPreviousPage()} onClick={() => table.setPageIndex(0)}><ChevronsLeft size={16}/></button><button className="icon-button" aria-label="Previous page" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}><ChevronLeft size={16}/></button><button className="icon-button" aria-label="Next page" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}><ChevronRight size={16}/></button><button className="icon-button" aria-label="Last page" disabled={!table.getCanNextPage()} onClick={() => table.setPageIndex(table.getPageCount()-1)}><ChevronsRight size={16}/></button></div></div>
    {selected.length>0&&<div className="bulk-toolbar" role="region" aria-label="Selected findings actions"><span className="bulk-count"><Check size={16}/><strong>{selected.length}</strong>selected</span><button className="button primary" onClick={() => openReview(selected)}><FileCode2 size={16}/>Review code<span className="shortcut-hint">⇧ R</span></button><button className="button bulk-secondary" onClick={() => exportSelection('csv')}><Download size={15}/>CSV</button><button className="button bulk-secondary" onClick={() => exportSelection('json')}>JSON</button><button className="icon-button" aria-label="Clear selected findings" onClick={() => table.resetRowSelection()}><X size={17}/></button></div>}
  </section>;
}
