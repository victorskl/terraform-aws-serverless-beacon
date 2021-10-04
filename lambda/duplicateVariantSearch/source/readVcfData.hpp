#pragma once

#include <awsutils.hpp>
#include <generalutils.hpp>
#include <deque>
#include <gzip.hpp>

#define BUFFER_SIZE 1024
constexpr size_t MIN_DATA_SIZE = sizeof(generalutils::vcfData::pos) + 4;

struct vcfRegionData  { 
    string filepath; 
    uint16_t contig;
    uint64_t startRange;
    uint64_t endRange;
};

class ReadVcfData {
    private:
    static string readString(size_t &bufferPos, gzip &inputGzip, size_t &dataLength, char *streamBuffer);
    static bool checkForAvailableData(size_t bytesNeeded, size_t &bufferPos, gzip &inputGzip, size_t &dataLength);

    public:
    static deque<generalutils::vcfData> getVcfData(Aws::String bucket, Aws::String targetFilepath, Aws::S3::S3Client &client, uint64_t rangeStart, uint64_t rangeEnd);
};
