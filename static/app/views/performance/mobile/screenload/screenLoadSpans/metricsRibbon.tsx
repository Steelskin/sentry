import type {ComponentProps} from 'react';
import {useMemo} from 'react';
import styled from '@emotion/styled';

import type {Polarity} from 'sentry/components/percentChange';
import {space} from 'sentry/styles/space';
import type {NewQuery} from 'sentry/types/organization';
import type {TableData, TableDataRow} from 'sentry/utils/discover/discoverQuery';
import EventView from 'sentry/utils/discover/eventView';
import type {DiscoverDatasets} from 'sentry/utils/discover/types';
import {MutableSearch} from 'sentry/utils/tokenizeSearch';
import {useLocation} from 'sentry/utils/useLocation';
import usePageFilters from 'sentry/utils/usePageFilters';
import {MetricReadout} from 'sentry/views/performance/metricReadout';
import {useTableQuery} from 'sentry/views/performance/mobile/screenload/screens/screensTable';
import useCrossPlatformProject from 'sentry/views/performance/mobile/useCrossPlatformProject';
import {useReleaseSelection} from 'sentry/views/starfish/queries/useReleases';
import {appendReleaseFilters} from 'sentry/views/starfish/utils/releaseComparison';

interface BlockProps {
  dataKey: string | ((data?: TableDataRow[]) => number | undefined);
  title: string;
  unit: ComponentProps<typeof MetricReadout>['unit'];
  allowZero?: boolean;
  preferredPolarity?: Polarity;
}

export function MetricsRibbon({
  filters,
  blocks,
  fields,
  referrer,
  dataset,
}: {
  blocks: BlockProps[];
  dataset: DiscoverDatasets;
  fields: string[];
  referrer: string;
  filters?: string[];
}) {
  const {selection} = usePageFilters();
  const location = useLocation();

  const {
    primaryRelease,
    secondaryRelease,
    isLoading: isReleasesLoading,
  } = useReleaseSelection();

  const {isProjectCrossPlatform, selectedPlatform} = useCrossPlatformProject();

  const queryString = useMemo(() => {
    const searchQuery = new MutableSearch([...(filters ?? [])]);

    if (isProjectCrossPlatform) {
      searchQuery.addFilterValue('os.name', selectedPlatform);
    }

    return appendReleaseFilters(searchQuery, primaryRelease, secondaryRelease);
  }, [
    filters,
    isProjectCrossPlatform,
    primaryRelease,
    secondaryRelease,
    selectedPlatform,
  ]);

  const newQuery: NewQuery = {
    name: 'ScreenMetricsRibbon',
    fields,
    query: queryString,
    dataset,
    version: 2,
    projects: selection.projects,
  };
  const eventView = EventView.fromNewQueryWithLocation(newQuery, location);
  const {data, isLoading} = useTableQuery({
    eventView,
    enabled: !isReleasesLoading,
    referrer,
  });

  return (
    <BlockContainer>
      {blocks.map(({title, dataKey, unit, preferredPolarity}) => (
        <MetricsBlock
          key={title}
          title={title}
          unit={unit}
          dataKey={dataKey}
          data={data}
          isLoading={isLoading}
          preferredPolarity={preferredPolarity}
        />
      ))}
    </BlockContainer>
  );
}

function MetricsBlock({
  title,
  unit,
  data,
  dataKey,
  isLoading,
  allowZero,
  preferredPolarity,
}: {
  isLoading: boolean;
  title: string;
  data?: TableData;
  release?: string;
} & BlockProps) {
  const value =
    typeof dataKey === 'function'
      ? dataKey(data?.data)
      : (data?.data?.[0]?.[dataKey] as number);

  const hasData = (value && value !== 0) || (value === 0 && allowZero);

  return (
    <MetricReadout
      title={title}
      align="left"
      value={hasData ? value : undefined}
      isLoading={isLoading}
      unit={unit}
      preferredPolarity={preferredPolarity}
    />
  );
}

const BlockContainer = styled('div')`
  display: flex;
  gap: ${space(2)};
`;
