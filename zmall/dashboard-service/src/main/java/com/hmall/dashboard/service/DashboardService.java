package com.hmall.dashboard.service;

import com.hmall.api.client.ItemClient;
import com.hmall.api.client.SocialClient;
import com.hmall.api.client.TradeClient;
import com.hmall.api.dto.FansStatsDTO;
import com.hmall.api.dto.OrderStatsDTO;
import com.hmall.api.dto.SalesTrendDTO;
import com.hmall.api.dto.TopItemDTO;
import com.hmall.dashboard.domain.dto.DashboardDTO;
import com.hmall.dashboard.domain.dto.SeckillStatsDTO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class DashboardService {

    private final TradeClient tradeClient;
    private final SocialClient socialClient;
    private final ItemClient itemClient;

    public DashboardDTO getTodayOverview() {
        OrderStatsDTO apiStats = tradeClient.getMerchantOrderStats();
        FansStatsDTO fansStats = socialClient.getFansStats();

        DashboardDTO dto = new DashboardDTO();
        dto.setTodayOrders(apiStats.getTodayNew());
        dto.setTodaySales(apiStats.getTodaySales());
        dto.setPendingShip(apiStats.getPendingShip());
        dto.setTotalItems(itemClient.countByStatus(1));
        dto.setTotalFans(fansStats.getTotalFans());
        dto.setTodayNewFans(fansStats.getTodayNew());
        dto.setSeckillRate(0.0);
        return dto;
    }

    public List<SalesTrendDTO> getSalesTrend(Integer days) {
        return tradeClient.getSalesTrend(days);
    }

    public List<TopItemDTO> getTopItems(Integer limit) {
        return tradeClient.getTopItems(limit);
    }

    public List<SeckillStatsDTO> getSeckillStats() {
        return List.of();
    }
}
